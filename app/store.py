"""Persistencia SQLite del panel (volumen persistente en /data/panel.db)."""
import os
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats(
  id TEXT NOT NULL,
  line TEXT NOT NULL,
  name TEXT,
  phone TEXT,
  phone_last4 TEXT,
  last_ts INTEGER,
  last_from_me INTEGER,
  last_body TEXT,
  last_has_media INTEGER,
  last_media_type TEXT,
  sent_count INTEGER DEFAULT 0,
  recv_count INTEGER DEFAULT 0,
  last_out_ts INTEGER,
  last_in_ts INTEGER,
  last_in_body TEXT,
  last_out_body TEXT,
  responded INTEGER DEFAULT 0,
  human_count INTEGER DEFAULT 0,
  auto_count INTEGER DEFAULT 0,
  last_in_auto INTEGER,
  is_prospect INTEGER DEFAULT 0,
  threaded INTEGER DEFAULT 0,
  lead_id TEXT,
  updated_at INTEGER,
  PRIMARY KEY(id, line)
);
CREATE TABLE IF NOT EXISTS messages(
  msg_id TEXT PRIMARY KEY,
  chat_id TEXT,
  line TEXT,
  ts INTEGER,
  from_me INTEGER,
  body TEXT,
  has_media INTEGER,
  media_type TEXT,
  auto INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, line, ts);
-- Clasificación manual de un mensaje entrante (corrige la heurística). Si existe una
-- fila aquí, MANDA sobre la columna `messages.auto`: no se vuelve a clasificar.
CREATE TABLE IF NOT EXISTS msg_manual(
  msg_id TEXT PRIMARY KEY,
  es_auto INTEGER NOT NULL,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS leads(
  id TEXT PRIMARY KEY,
  nombre TEXT,
  norm TEXT,
  tipo TEXT,
  zona TEXT,
  estado TEXT,
  mensajes_enviados INTEGER,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
-- Datos propios del panel (no existen en Radar): estados finos, notas y las tres
-- fechas curadas/deducidas por cliente. La clave es el id de chat de WAHA
-- («506...@c.us») o, para un lead sin conversación, «lead:<id>».
CREATE TABLE IF NOT EXISTS clientes(
  key TEXT PRIMARY KEY,
  nombre TEXT,
  interesado_el TEXT,
  demo_enviado_el TEXT,
  cotizacion_enviada_el TEXT,
  estado_extra TEXT,
  nota TEXT,
  -- Corrección manual «este cliente es solo automáticas» (manda sobre la heurística):
  -- NULL = lo decide la heurística, 1 = marcado a mano como solo automáticas,
  -- 0 = marcado a mano como respuesta real.
  solo_auto INTEGER,
  updated_at INTEGER
);
"""

# Columnas añadidas después de la primera versión: se aplican con ALTER TABLE sobre la
# base ya existente (CREATE TABLE IF NOT EXISTS no toca una tabla que ya está).
MIGRATIONS = {
    "messages": {"auto": "INTEGER DEFAULT 0"},
    "chats": {
        "human_count": "INTEGER DEFAULT 0",
        "auto_count": "INTEGER DEFAULT 0",
        "last_in_auto": "INTEGER",
    },
    "clientes": {"solo_auto": "INTEGER"},
}


def _migrate(conn):
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def connect():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        with _lock, _conn:
            _conn.executescript(SCHEMA)
            _migrate(_conn)
    return _conn


def query(sql, args=()):
    c = connect()
    with _lock:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql, args=()):
    c = connect()
    with _lock, c:
        return c.execute(sql, args)


def executemany(sql, rows):
    c = connect()
    with _lock, c:
        return c.executemany(sql, rows)


def set_meta(key, value):
    execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


def get_meta(key, default=None):
    rows = query("SELECT value FROM meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def now():
    return int(time.time())


# --------------------------------------------------------------- clientes (datos del panel)

CLIENTE_FIELDS = (
    "nombre",
    "interesado_el",
    "demo_enviado_el",
    "cotizacion_enviada_el",
    "estado_extra",
    "nota",
    "solo_auto",
)


def cliente_get(key):
    if not key:
        return None
    rows = query("SELECT * FROM clientes WHERE key=?", (key,))
    return rows[0] if rows else None


def cliente_all():
    return {r["key"]: r for r in query("SELECT * FROM clientes")}


def _cliente_write(key, row):
    execute(
        """INSERT INTO clientes(key,nombre,interesado_el,demo_enviado_el,cotizacion_enviada_el,
                estado_extra,nota,solo_auto,updated_at)
           VALUES(:key,:nombre,:interesado_el,:demo_enviado_el,:cotizacion_enviada_el,
                :estado_extra,:nota,:solo_auto,:updated_at)
           ON CONFLICT(key) DO UPDATE SET
                nombre=excluded.nombre, interesado_el=excluded.interesado_el,
                demo_enviado_el=excluded.demo_enviado_el,
                cotizacion_enviada_el=excluded.cotizacion_enviada_el,
                estado_extra=excluded.estado_extra, nota=excluded.nota,
                solo_auto=excluded.solo_auto,
                updated_at=excluded.updated_at""",
        row,
    )


def cliente_upsert(key, values, overwrite=True):
    """Upsert por clave. Nunca borra lo que ya había si el campo viene vacío.

    overwrite=True  -> un valor nuevo no vacío reemplaza al anterior (ingesta curada).
    overwrite=False -> solo rellena campos que estaban vacíos (fechas deducidas de WAHA).
    """
    if not key:
        return False
    cur = cliente_get(key) or {}
    row = {"key": key, "updated_at": now()}
    changed = False
    for f in CLIENTE_FIELDS:
        old = cur.get(f)
        new = values.get(f)
        if new in (None, ""):
            row[f] = old
        elif overwrite or old in (None, ""):
            row[f] = new
            changed = changed or (new != old)
        else:
            row[f] = old
    if cur:
        row["key"] = key
        _cliente_write(key, row)
        return True
    if not any(row.get(f) not in (None, "") for f in CLIENTE_FIELDS):
        return False  # nada que crear
    _cliente_write(key, row)
    return True


def cliente_set(key, values):
    """Escritura manual: solo escribe las claves presentes en `values` (permite vaciar)."""
    if not key:
        return None
    cur = cliente_get(key) or {}
    row = {"key": key, "updated_at": now()}
    for f in CLIENTE_FIELDS:
        row[f] = values[f] if f in values else cur.get(f)
    _cliente_write(key, row)
    return cliente_get(key)


def cliente_delete(key):
    if not key:
        return False
    execute("DELETE FROM clientes WHERE key=?", (key,))
    return True
