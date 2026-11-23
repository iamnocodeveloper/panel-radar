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
    now_ts = store.now()
    existing = {r["id"]: r for r in store.query("SELECT id, threaded FROM chats WHERE line=?", (name,))}
    candidates = []
    for chat in overview:
        lm = chat.get("lastMessage") or {}
        cid = chat.get("id")
        recent = (chat.get("conversationTimestamp") or 0) > now_ts - 45 * 86400
        if lm.get("fromMe") or recent or existing.get(cid, {}).get("is_prospect"):
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
    out = {"ok": True}
    try:
        out["resumen"] = sync_radar()
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(_sync_line, config.lines()))
        match_leads()
        store.execute("UPDATE chats SET is_prospect=1 WHERE lead_id IS NOT NULL")
        store.set_meta("last_refresh", store.now())
        out["elapsed"] = round(time.time() - t0, 1)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": str(e)[:300]}
        store.set_meta("last_error", str(e)[:300])
    finally:
        store.set_meta("refreshing", "0")
    return out
