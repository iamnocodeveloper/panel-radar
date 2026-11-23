"""Sincronización: Radar + las dos líneas de WAHA -> SQLite."""
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from . import clients, config, store

MEDIA_LABEL = {
    "image": "imagen",
    "video": "video",
    "audio": "audio",
    "application": "documento",
    "sticker": "sticker",
    "text": "texto",
}

# Un enlace a una demo publicada por nosotros lleva el dominio de EasyPanel.
DEMO_LINK = re.compile(r"easypanel\.host", re.IGNORECASE)
# Un envío con precios / propuesta cuenta como cotización.
PRICE_WORDS = re.compile(r"\$\s?\d|cotiza|propuesta", re.IGNORECASE)
DEMO_MEDIA = ("imagen", "documento")
# Un saludo automático del negocio llega en segundos tras nuestro primer mensaje.
# No cuenta como «se interesó» (ver `derive_dates`).
AUTO_ACK_SECONDS = 60


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def media_label(msg):
    m = msg.get("media") or {}
    mime = (m.get("mimetype") or "").lower()
    if msg.get("hasMedia"):
        if not mime:
            return "multimedia"
        head = mime.split("/")[0]
        if head == "application" and "pdf" in mime:
            return "documento"
        return MEDIA_LABEL.get(head, "multimedia")
    if msg.get("location"):
        return "ubicacion"
    if msg.get("vCards"):
        return "contacto"
    return "texto"


def _phones(chat_id):
    num = (chat_id or "").split("@")[0]
    num = re.sub(r"\D", "", num)
    last4 = num[-4:] if len(num) >= 4 else num
    return num, last4


# --------------------------------------------------------------- fechas por cliente

_EC = None


def _iso(ts):
    global _EC
    if not ts:
        return None
    if _EC is None:
        from datetime import timedelta, timezone

        _EC = timezone(timedelta(seconds=config.TZ_OFFSET))
    from datetime import datetime

    return datetime.fromtimestamp(int(ts), _EC).isoformat()


def derive_dates(msgs):
    """Deduce las tres fechas de un hilo, mezclando mensajes de WAHA y filas de SQLite.

    - interesado_el: instante del PRIMER mensaje entrante (fromMe=false) del hilo. Se
      descarta el saludo automático del negocio (autorespuesta que llega en segundos
      tras nuestro primer mensaje) cuando hay un mensaje entrante posterior: el cliente
      «se interesó» cuando escribió de verdad, no cuando contestó su robot.
    - demo_enviado_el: primer envío nuestro con multimedia (imagen/documento) y enlace
      easypanel.host; si no hay enlace, el primer envío de imagen/documento.
    - cotizacion_enviada_el: primer envío nuestro con precios / «cotiza» / «propuesta».
    """
    ins, outs = [], []
    for m in msgs:
        ts = m.get("ts") if "ts" in m else m.get("timestamp")
        if not ts:
            continue
        fm = m.get("from_me") if "from_me" in m else m.get("fromMe")
        body = m.get("body") or ""
        mt = m.get("media_type")
        if mt is None:
            mt = media_label(m) if (m.get("hasMedia") or m.get("has_media")) else None
        (outs if fm else ins).append((int(ts), body, mt))

    in_ts = [t for t, _b, _m in ins]
    out_ts = [t for t, _b, _m in outs]

    def _auto_ack(t_in):
        prev = [t for t in out_ts if t <= t_in]
        if not prev or t_in - max(prev) > AUTO_ACK_SECONDS:
            return False
        # solo se descarta si hay un entrante posterior que represente el interés real
        return any(t > t_in for t in in_ts)

    human_in = [t for t in in_ts if not _auto_ack(t)]
    interesado = min(human_in, default=None)
    if interesado is None:
        interesado = min(in_ts, default=None)
    with_link = [t for t, b, m in outs if m in DEMO_MEDIA and DEMO_LINK.search(b)]
    media_only = [t for t, _b, m in outs if m in DEMO_MEDIA]
    demo = min(with_link) if with_link else (min(media_only) if media_only else None)
    cot = [t for t, b, _m in outs if PRICE_WORDS.search(b)]
    cotizacion = min(cot) if cot else None

    return {
        "interesado_el": _iso(interesado),
        "demo_enviado_el": _iso(demo),
        "cotizacion_enviada_el": _iso(cotizacion),
    }


def _chat_id_from_key(key):
    """Saca el id de chat de una clave de la tabla `clientes`.

    Admite el id desnudo («506...@c.us») y el formato antiguo «chat:<linea>:<chatId>».
    Devuelve None para claves de lead («lead:<id>») o que no son un chat.
    """
    if not key:
        return None
    if key.startswith("lead:"):
        return None
    if key.startswith("chat:"):
        partes = key.split(":", 2)
        key = partes[2] if len(partes) == 3 else key
    return key if "@" in key else None


def autofill_dates():
    """Rellena las fechas deducidas de CADA conversación que exista, sin pisar lo

    que ya haya (ni lo curado desde fuera ni lo que Joel fijó a mano). Incluye tanto
    las conversaciones de prospecto/lead como las que tienen una fila curada en
    `clientes` (p. ej. un cliente empujado desde fuera al que le mandamos el demo).
    """
    rows = store.query(
        "SELECT DISTINCT id, line FROM chats WHERE is_prospect=1 OR lead_id IS NOT NULL"
    )
    vistos = {(r["id"], r["line"]) for r in rows}
    rows = list(rows)
    for r in store.query("SELECT key FROM clientes"):
        cid = _chat_id_from_key(r["key"])
        if not cid:
            continue
        for ch in store.query("SELECT id, line FROM chats WHERE id=?", (cid,)):
            if (ch["id"], ch["line"]) not in vistos:
                vistos.add((ch["id"], ch["line"]))
                rows.append(ch)
    n = 0
    for r in rows:
        msgs = store.query(
            "SELECT ts, from_me, body, media_type FROM messages "
            "WHERE chat_id=? AND line=? ORDER BY ts ASC",
            (r["id"], r["line"]),
        )
        if not msgs:
            continue
        derived = derive_dates(msgs)
        if any(derived.values()):
            store.cliente_upsert(r["id"], derived, overwrite=False)
            n += 1
    return n


# --------------------------------------------------------------- Radar

def sync_radar():
    data = clients.radar_today()
    resumen = data.get("resumen", {})
    leads = (data.get("seguimientos") or []) + (data.get("nuevos") or [])
    rows = []
    for s in leads:
        rows.append(
            (
                s.get("id"),
                s.get("nombre"),
                norm(s.get("nombre")),
                s.get("tipo"),
                s.get("zona"),
                s.get("estado"),
                s.get("mensajesEnviados"),
                store.now(),
            )
        )
    if rows:
        store.executemany(
            """INSERT INTO leads(id,nombre,norm,tipo,zona,estado,mensajes_enviados,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 nombre=excluded.nombre, norm=excluded.norm, tipo=excluded.tipo,
                 zona=excluded.zona, estado=excluded.estado,
                 mensajes_enviados=excluded.mensajes_enviados, updated_at=excluded.updated_at""",
            rows,
        )
    store.set_meta("resumen", __import__("json").dumps(resumen, ensure_ascii=False))
    return resumen


# --------------------------------------------------------------- WAHA

def _chat_row(line_name, chat, thread_msgs):
    """Construye/actualiza la fila de un chat a partir del overview + hilo."""
    cid = chat.get("id")
    lm = chat.get("lastMessage") or {}
    phone, last4 = _phones(cid)
    now = store.now()

    sent = recv = 0
    last_out_ts = None
    last_in_ts = None
    last_out_body = None
    last_in_body = None
    first_out_ts = None
    bodies_out = []
    for m in thread_msgs:
        ts = m.get("timestamp")
        if m.get("fromMe"):
            sent += 1
            if ts:
                if last_out_ts is None or ts >= last_out_ts:
                    last_out_ts = ts
                    last_out_body = m.get("body")
                if first_out_ts is None or ts < first_out_ts:
                    first_out_ts = ts
            if m.get("body"):
                bodies_out.append(m["body"])
        else:
            recv += 1
            if ts and (last_in_ts is None or ts >= last_in_ts):
                last_in_ts = ts
                last_in_body = m.get("body")

    # El cliente "respondió" si escribió ALGUNO de sus mensajes después de nuestro
    # primer contacto (un seguimiento posterior nuestro no borra la respuesta).
    responded = 1 if (first_out_ts and any(
        (m.get("timestamp") or 0) > first_out_ts for m in thread_msgs if not m.get("fromMe")
    )) else 0
    is_prospect = 0
    low = " ".join(bodies_out).lower()
    if "nocodeveloper" in low:
        is_prospect = 1

    return {
        "id": cid,
        "line": line_name,
        "name": chat.get("name"),
        "phone": phone,
        "phone_last4": last4,
        "last_ts": lm.get("timestamp"),
        "last_from_me": 1 if lm.get("fromMe") else 0,
        "last_body": lm.get("body"),
        "last_has_media": 1 if lm.get("hasMedia") else 0,
        "last_media_type": media_label(lm),
        "sent_count": sent,
        "recv_count": recv,
        "last_out_ts": last_out_ts,
        "last_in_ts": last_in_ts,
        "last_in_body": last_in_body,
        "last_out_body": last_out_body,
        "responded": responded,
        "is_prospect": is_prospect,
        "threaded": 1,
        "updated_at": now,
    }


def _sync_line(line):
    name = line["nombre"]
    try:
        sess = clients.waha_session(line)
        status = sess.get("status")
        me = (sess.get("me") or {}).get("id")
    except Exception as e:  # noqa: BLE001
        store.set_meta(f"line_{name}", __import__("json").dumps({"status": "ERROR", "error": str(e)[:200]}))
        return
    store.set_meta(f"line_{name}", __import__("json").dumps({"status": status, "me": me}))

    try:
        overview = clients.waha_overview(line)
    except Exception:
        return

    # Solo hilos de chats que escribimos o con actividad reciente (evita personales antiguos).
    # Ojo: WAHA a veces deja `conversationTimestamp` en None (p. ej. chats contactados por
    # API): en ese caso la recencia se mide con el timestamp del último mensaje, que es lo
    # que de verdad importa. Y un chat curado en `clientes` siempre se sincroniza.
    now_ts = store.now()
    existing = {r["id"]: r for r in store.query("SELECT id, threaded FROM chats WHERE line=?", (name,))}
    curados = {c["key"] for c in store.query("SELECT key FROM clientes")}
    candidates = []
    for chat in overview:
        lm = chat.get("lastMessage") or {}
        cid = chat.get("id")
        last_act = lm.get("timestamp") or chat.get("conversationTimestamp") or 0
        recent = last_act > now_ts - 45 * 86400
        if (
            lm.get("fromMe")
            or recent
            or existing.get(cid, {}).get("is_prospect")
            or cid in curados
        ):
            candidates.append(chat)

    def fetch(chat):
        try:
            return chat, clients.waha_messages(line, chat["id"])
        except Exception:  # noqa: BLE001
            return chat, None

    rows = []
    msgs = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for chat, thread in ex.map(fetch, candidates):
            if thread is None:
                continue
            row = _chat_row(name, chat, thread)
            rows.append(row)
            for m in thread:
                if not m.get("id"):
                    continue
                msgs.append(
                    (
                        m.get("id"),
                        chat["id"],
                        name,
                        m.get("timestamp"),
                        1 if m.get("fromMe") else 0,
                        m.get("body"),
                        1 if m.get("hasMedia") else 0,
                        media_label(m),
                    )
                )

    if msgs:
        store.executemany(
            """INSERT OR REPLACE INTO messages(msg_id,chat_id,line,ts,from_me,body,has_media,media_type)
               VALUES(?,?,?,?,?,?,?,?)""",
            msgs,
        )
    if rows:
        store.executemany(
            """INSERT INTO chats(id,line,name,phone,phone_last4,last_ts,last_from_me,last_body,
                    last_has_media,last_media_type,sent_count,recv_count,last_out_ts,last_in_ts,
                    last_in_body,last_out_body,responded,is_prospect,threaded,updated_at)
               VALUES(:id,:line,:name,:phone,:phone_last4,:last_ts,:last_from_me,:last_body,
                    :last_has_media,:last_media_type,:sent_count,:recv_count,:last_out_ts,:last_in_ts,
                    :last_in_body,:last_out_body,:responded,:is_prospect,:threaded,:updated_at)
               ON CONFLICT(id,line) DO UPDATE SET
                    name=excluded.name, phone=excluded.phone, phone_last4=excluded.phone_last4,
                    last_ts=excluded.last_ts, last_from_me=excluded.last_from_me,
                    last_body=excluded.last_body, last_has_media=excluded.last_has_media,
                    last_media_type=excluded.last_media_type, sent_count=excluded.sent_count,
                    recv_count=excluded.recv_count, last_out_ts=excluded.last_out_ts,
                    last_in_ts=excluded.last_in_ts, last_in_body=excluded.last_in_body,
                    last_out_body=excluded.last_out_body, responded=excluded.responded,
                    is_prospect=excluded.is_prospect, threaded=excluded.threaded,
                    updated_at=excluded.updated_at""",
            rows,
        )


# --------------------------------------------------------------- Matching

def match_leads():
    leads = store.query("SELECT id,nombre,norm,zona,estado,tipo FROM leads WHERE norm IS NOT NULL AND norm<>''")
    by_norm = {}
    for l in leads:
        by_norm.setdefault(l["norm"], l)
    norm_names = [(l["norm"], l) for l in leads]

    chats = store.query("SELECT id,line,name FROM chats WHERE is_prospect=1 OR threaded=1")
    for ch in chats:
        cid, line = ch["id"], ch["line"]
        name = ch["name"]
        matched = None
        cname = norm(name)
        if cname and cname in by_norm:
            matched = by_norm[cname]
        else:
            # contención por nombre de chat
            if cname and len(cname) >= 8:
                for ln, l in norm_names:
                    if len(ln) >= 8 and (ln in cname or cname in ln) and abs(len(ln) - len(cname)) <= 12:
                        matched = l
                        break
            if matched is None:
                # buscar el nombre del negocio dentro de NUESTROS mensajes
                outs = store.query(
                    "SELECT body FROM messages WHERE chat_id=? AND line=? AND from_me=1 AND body IS NOT NULL",
                    (cid, line),
                )
                if outs:
                    text = " " + " ".join(norm(r["body"]) for r in outs) + " "
                    best = None
                    for ln, l in norm_names:
                        if len(ln) >= 6 and f" {ln} " in text:
                            if best is None or len(ln) > len(norm(best["nombre"])):
                                best = l
                    matched = best
        store.execute(
            "UPDATE chats SET lead_id=? WHERE id=? AND line=?",
            (matched["id"] if matched else None, cid, line),
        )


def refresh():
    if store.get_meta("refreshing") == "1":
        return {"ok": False, "reason": "ya en curso"}
    store.set_meta("refreshing", "1")
    t0 = time.time()
    out = {"ok": True}  # type: dict
    try:
        out["resumen"] = sync_radar()
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(_sync_line, config.lines()))
        match_leads()
        store.execute("UPDATE chats SET is_prospect=1 WHERE lead_id IS NOT NULL")
        out["fechas"] = autofill_dates()
        store.set_meta("last_refresh", store.now())
        out["elapsed"] = round(time.time() - t0, 1)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": str(e)[:300]}
        store.set_meta("last_error", str(e)[:300])
    finally:
        store.set_meta("refreshing", "0")
    return out
