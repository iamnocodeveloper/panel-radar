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
  media_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, line, ts);
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
"""


def connect():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        with _lock, _conn:
            _conn.executescript(SCHEMA)
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
