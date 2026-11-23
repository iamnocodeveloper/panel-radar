"""Pruebas locales: clasificación auto/humano, kanban «solo auto» y fechas.

No toca la red: siembra una SQLite de prueba y ejercita las funciones puras.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="radartest")
os.environ["DB_PATH"] = os.path.join(TMP, "panel.db")
os.environ["PANEL_CAPI_USER"] = "admin"
os.environ["PANEL_CAPI_PASS"] = "secret"
os.environ["INGEST_KEY"] = "ingest-secret-key-123456"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store, sync, main  # noqa: E402
from app.sync import clasificar_auto  # noqa: E402

# --- 1. clasificación del texto
casos = [
    ("Gracias por su mensaje, en breve le atenderemos", 1),
    ("Gracias por  comunicarte con la Secretaria", 1),
    ("¡Bienvenido! Nuestro horario de atención es 8 a 5", 1),
    ("Este es un mensaje automático, deje su mensaje y le responderemos", 1),
    ("Estoy fuera de horario, escríbanos mañana", 1),
    ("Soy un asistente virtual, puede dejarnos su consulta", 1),
    ("Hola, buenas tardes", 0),
    ("Buenos días, ¿me puede enviar el catálogo?", 0),
    ("Sí, me interesa, ¿cuánto cuesta?", 0),
    ("Ok, gracias", 0),
    ("hola", 0),
]
print("== clasificar_auto ==")
fallos = 0
for txt, esperado in casos:
    got = clasificar_auto(txt)
    ok = "OK " if got == esperado else "FALLA"
    if got != esperado:
        fallos += 1
    print(f"  {ok} [{got}] {txt!r}")

# --- 2. derive_dates: primero bot, después persona -> la fecha es la humana
BOT = 1_700_000_000
HUM = BOT + 3600
msgs = [
    {"ts": BOT - 100, "from_me": 1, "body": "Hola, le escribo de nocodeveloper", "auto": 0},
    {"ts": BOT, "from_me": 0, "body": "Gracias por su mensaje, en breve le atenderemos", "auto": 1},
    {"ts": HUM, "from_me": 0, "body": "Buenas, ¿me manda el link del demo?", "auto": 0},
]
d = sync.derive_dates(msgs)
from datetime import datetime, timedelta, timezone  # noqa: E402

EC = timezone(timedelta(seconds=-5 * 3600))
esperado = datetime.fromtimestamp(HUM, EC).isoformat()
print("\n== derive_dates ==")
print("  interesado_el:", d["interesado_el"], "(esperado", esperado + ")")
assert d["interesado_el"] == esperado, "la fecha debe ser la del mensaje HUMANO"

# --- 3. kanban: cliente con bot + persona (caso mixto) y cliente solo bot
store.connect()
now = int(datetime.now(EC).timestamp())
store.execute("INSERT INTO leads(id,nombre,norm,estado,mensajes_enviados) VALUES(?,?,?,?,?)",
              ("L-REAL", "Pizza Real", "pizza real", "contactado", 1))
store.execute("INSERT INTO leads(id,nombre,norm,estado,mensajes_enviados) VALUES(?,?,?,?,?)",
              ("L-BOT", "Tienda Bot", "tienda bot", "contactado", 1))
chats = [
    # (chat_id, lead, msgs): primero bot luego persona
    ("50610000001@c.us", "L-REAL"),
    ("50610000002@c.us", "L-BOT"),
]
for cid, lead in chats:
    store.execute(
        "INSERT INTO chats(id,line,name,phone_last4,last_ts,last_from_me,last_body,"
        "sent_count,recv_count,responded,is_prospect,threaded,lead_id,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,1,1,?,?)",
        (cid, "principal", lead, "0001", now, 0, "x", 1, 1, 0, lead, now),
    )
def addmsg(mid, cid, ts, fm, body):
    store.execute(
        "INSERT INTO messages(msg_id,chat_id,line,ts,from_me,body,has_media,media_type,auto)"
        " VALUES(?,?,?,?,?,?,0,'texto',?)",
        (mid, cid, "principal", ts, fm, body, clasificar_auto(body)),
    )
addmsg("m1", "50610000001@c.us", now - 300, 1, "Hola, le escribo de nocodeveloper")
addmsg("m2", "50610000001@c.us", now - 200, 0, "Gracias por su mensaje, en breve le atenderemos")
addmsg("m3", "50610000001@c.us", now - 100, 0, "Buenas, mándeme el demo por favor")
addmsg("m4", "50610000002@c.us", now - 300, 1, "Hola, le escribo de nocodeveloper")
addmsg("m5", "50610000002@c.us", now - 200, 0, "Gracias por su mensaje, en breve le atenderemos")
sync.recomputar_respuestas()

kb = main.build_kanban()
por_nombre = {c["nombre"]: c for c in kb["cards"]}
real, bot = por_nombre["Pizza Real"], por_nombre["Tienda Bot"]
print("\n== kanban ==")
print("  Pizza Real:", real["estado"], "solo_auto=", real["solo_auto"], "h=", real["human_count"], "a=", real["auto_count"])
print("  Tienda Bot:", bot["estado"], "solo_auto=", bot["solo_auto"], "h=", bot["human_count"], "a=", bot["auto_count"])
assert real["estado"] == "respondio" and real["solo_auto"] is False
assert bot["estado"] == "contactado" and bot["solo_auto"] is True

# --- 4. resumen
res = main.build_resumen()
print("\n== resumen ==")
print("  contactados:", res["prospectos_contactados"], "reales:", res["prospectos_respondieron"],
      "auto:", res["prospectos_respondieron_auto"], "total:", res["prospectos_respondieron_total"],
      "tasa:", res["tasa_respuesta"], "tasa_total:", res["tasa_respuesta_total"])
assert res["prospectos_respondieron"] == 1
assert res["prospectos_respondieron_auto"] == 1
assert res["tasa_respuesta"] == 50.0

# --- 5. corrección manual: marcar el humano como automático -> pasa a contactado
store.execute("INSERT OR REPLACE INTO msg_manual(msg_id,es_auto,updated_at) VALUES(?,?,?)", ("m3", 1, now))
sync.recomputar_respuestas()
kb2 = main.build_kanban()
real2 = {c["nombre"]: c for c in kb2["cards"]}["Pizza Real"]
print("\n== corrección manual (m3 -> auto) ==")
print("  Pizza Real:", real2["estado"], "solo_auto=", real2["solo_auto"])
assert real2["estado"] == "contactado" and real2["solo_auto"] is True
store.execute("DELETE FROM msg_manual WHERE msg_id=?", ("m3",))
sync.recomputar_respuestas()

# --- 6. override a nivel de cliente: forzar «no solo auto» en el de bot
main.store.cliente_set("50610000002@c.us", {"solo_auto": 0})
kb3 = main.build_kanban()
bot3 = {c["nombre"]: c for c in kb3["cards"]}["Tienda Bot"]
print("\n== override cliente (solo_auto=0) ==")
print("  Tienda Bot:", bot3["estado"], "solo_auto=", bot3["solo_auto"])
assert bot3["estado"] == "respondio" and bot3["solo_auto"] is False

print("\nTODAS LAS PRUEBAS OK" if fallos == 0 else f"\n{fallos} FALLOS DE CLASIFICACIÓN")
