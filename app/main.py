"""Panel de prospección Radar + WhatsApp — API FastAPI (solo lectura, salvo estado en Radar)."""
import base64
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import clients, config, store, sync

EC = timezone(timedelta(hours=-5))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

ESTADOS = ["nuevo", "contactado", "respondio", "reunion", "cliente", "descartado"]

app = FastAPI(title="Panel Radar", docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------- Auth

def _check_auth(request: Request):
    if not config.PANEL_PASS:
        return True
    hdr = request.headers.get("authorization", "")
    if not hdr.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(hdr.split(" ", 1)[1]).decode("utf-8", "replace")
        user, _, pw = raw.partition(":")
    except Exception:  # noqa: BLE001
        return False
    import hmac

    return hmac.compare_digest(user, config.PANEL_USER) and hmac.compare_digest(pw, config.PANEL_PASS)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _check_auth(request):
        return PlainTextResponse(
            "No autorizado", status_code=401, headers={"WWW-Authenticate": 'Basic realm="panel-radar"'}
        )
    return await call_next(request)


# --------------------------------------------------------------- helpers

def fmt_dt(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), EC).strftime("%d/%m %H:%M")


def fmt_full(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), EC).strftime("%d/%m/%Y %H:%M")


def day_ec(ts):
    return datetime.fromtimestamp(int(ts), EC).strftime("%Y-%m-%d")


def today_ec():
    return datetime.now(EC).strftime("%Y-%m-%d")


def trunc(s, n=120):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------- vistas

def line_statuses():
    out = {}
    for line in config.lines():
        raw = store.get_meta(f"line_{line['nombre']}")
        st = {"status": "SIN DATOS"}
        if raw:
            try:
                st = json.loads(raw)
            except Exception:  # noqa: BLE001
                pass
        out[line["nombre"]] = {"status": st.get("status"), "me": st.get("me")}
    return out


def build_resumen():
    today = today_ec()
    enviados = {}
    respuestas = {}
    for line in config.lines():
        n = line["nombre"]
        e = store.query(
            "SELECT COUNT(*) c FROM messages WHERE line=? AND from_me=1 AND ts>=?",
            (n, int(datetime.now(EC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())),
        )
        r = store.query(
            "SELECT COUNT(*) c FROM messages WHERE line=? AND from_me=0 AND ts>=?",
            (n, int(datetime.now(EC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())),
        )
        enviados[n] = e[0]["c"] if e else 0
        respuestas[n] = r[0]["c"] if r else 0

    esp = store.query("SELECT COUNT(*) c FROM chats WHERE is_prospect=1 AND responded=0")
    prosp = store.query("SELECT COUNT(*) c FROM chats WHERE is_prospect=1")
    resp = store.query("SELECT COUNT(*) c FROM chats WHERE is_prospect=1 AND responded=1")
    n_prosp = prosp[0]["c"] if prosp else 0
    n_resp = resp[0]["c"] if resp else 0
    clientes = store.query("SELECT COUNT(*) c FROM leads WHERE estado='cliente'")
    radar = json.loads(store.get_meta("resumen", "{}") or "{}")

    return {
        "enviados_hoy": enviados,
        "respuestas_hoy": respuestas,
        "esperando_respuesta": esp[0]["c"] if esp else 0,
        "prospectos_contactados": n_prosp,
        "prospectos_respondieron": n_resp,
        "tasa_respuesta": round(100.0 * n_resp / n_prosp, 1) if n_prosp else 0.0,
        "clientes_cerrados": clientes[0]["c"] if clientes else 0,
        "radar": radar,
        "lineas": line_statuses(),
    }


def _chat_embed(ch):
    return {
        "line": ch["line"],
        "phone_last4": ch["phone_last4"],
        "ultimo": trunc(ch["last_body"]) if ch.get("last_body") else None,
        "ultimo_ts": ch.get("last_ts"),
        "ultimo_fmt": fmt_dt(ch.get("last_ts")),
        "desde_cliente": not ch.get("last_from_me"),
        "media": ch.get("last_media_type") if ch.get("last_has_media") else None,
        "sent": ch.get("sent_count"),
        "recv": ch.get("recv_count"),
        "responded": bool(ch.get("responded")),
    }


def build_kanban():
    # conversaciones emparejadas con un lead -> adjuntar al lead
    chats = store.query("SELECT * FROM chats WHERE is_prospect=1 OR lead_id IS NOT NULL")
    by_lead = {}
    unmatched = []
    for ch in chats:
        if ch.get("lead_id"):
            cur = by_lead.get(ch["lead_id"])
            if cur is None or (ch.get("last_out_ts") or ch.get("last_ts") or 0) > (
                cur.get("last_out_ts") or cur.get("last_ts") or 0
            ):
                by_lead[ch["lead_id"]] = ch
        elif ch.get("is_prospect"):
            unmatched.append(ch)

    zones = set()
    cards = []
    for l in store.query("SELECT * FROM leads"):
        ch = by_lead.get(l["id"])
        zones.add(l.get("zona") or "—")
        # Estado efectivo para el kanban: si el lead sigue en «contactado» pero el
        # cliente ya contestó, la tarjeta va a la columna «respondió».
        radar_estado = l.get("estado") or "nuevo"
        eff = radar_estado
        if radar_estado == "contactado" and ch and ch.get("responded"):
            eff = "respondio"
        card = {
            "key": f"lead:{l['id']}",
            "lead_id": l["id"],
            "nombre": l.get("nombre"),
            "zona": l.get("zona"),
            "tipo": l.get("tipo"),
            "estado": eff,
            "radar_estado": radar_estado,
            "mensajes_enviados": l.get("mensajes_enviados"),
            "conversacion": _chat_embed(ch) if ch else None,
        }
        cards.append(card)

    for ch in unmatched:
        zones.add("—")
        cards.append(
            {
                "key": f"chat:{ch['line']}:{ch['id']}",
                "lead_id": None,
                "nombre": ch.get("name") or f"…{ch['phone_last4']}",
                "zona": None,
                "tipo": None,
                "estado": "sin_ficha",
                "mensajes_enviados": None,
                "conversacion": _chat_embed(ch),
            }
        )

    # ordenar: con conversación reciente primero, luego alfabético
    cards.sort(key=lambda c: (-(((c["conversacion"] or {}).get("ultimo_ts") or 0)), (c["nombre"] or "").lower()))

    counts = {e: 0 for e in ESTADOS + ["sin_ficha"]}
    for c in cards:
        counts[c["estado"]] = counts.get(c["estado"], 0) + 1

    return {"cards": cards, "counts": counts, "zonas": sorted(z for z in zones if z)}


# --------------------------------------------------------------- rutas

@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "last_refresh": store.get_meta("last_refresh"),
        "version": "1.0.0",
        "arrancado_en": ARRANCADO_EN,
    }


@app.get("/api/state")
def api_state():
    return {
        "resumen": build_resumen(),
        "kanban": build_kanban(),
        "last_refresh": store.get_meta("last_refresh"),
        "last_refresh_fmt": fmt_dt(store.get_meta("last_refresh")),
        "last_error": store.get_meta("last_error"),
        "refreshing": store.get_meta("refreshing") == "1",
    }


@app.get("/api/conversations")
def api_conversations(q: str = "", line: str = ""):
    sql = "SELECT * FROM chats WHERE is_prospect=1"
    args = []
    if line:
        sql += " AND line=?"
        args.append(line)
    rows = store.query(sql + " ORDER BY COALESCE(last_ts,0) DESC", args)
    out = []
    for ch in rows:
        lead = None
        if ch.get("lead_id"):
            l = store.query("SELECT nombre,estado,zona FROM leads WHERE id=?", (ch["lead_id"],))
            lead = l[0] if l else None
        item = {
            "chat_id": ch["id"],
            "line": ch["line"],
            "nombre": ch.get("name") or f"…{ch['phone_last4']}",
            "phone_last4": ch["phone_last4"],
            "estado": lead["estado"] if lead else "sin_ficha",
            "lead_nombre": lead["nombre"] if lead else None,
            "zona": lead["zona"] if lead else None,
            "ultimo": trunc(ch["last_body"]) if ch.get("last_body") else None,
            "ultimo_fmt": fmt_dt(ch.get("last_ts")),
            "ultimo_ts": ch.get("last_ts"),
            "desde_cliente": not ch.get("last_from_me"),
            "media": ch.get("last_media_type") if ch.get("last_has_media") else None,
            "sent": ch.get("sent_count"),
            "recv": ch.get("recv_count"),
            "responded": bool(ch.get("responded")),
        }
        out.append(item)
    if q:
        ql = sync.norm(q)
        out = [
            it
            for it in out
            if ql in sync.norm(it["nombre"])
            or ql in sync.norm(it.get("lead_nombre") or "")
            or ql in (it["phone_last4"] or "")
        ]
    return {"items": out}


@app.get("/api/chat/{line}/{chat_id}")
def api_chat(line: str, chat_id: str):
    msgs = store.query(
        "SELECT msg_id,ts,from_me,body,has_media,media_type FROM messages "
        "WHERE chat_id=? AND line=? ORDER BY ts ASC",
        (chat_id, line),
    )
    if not msgs:
        # intentar leer el hilo del tirón
        for ln in config.lines():
            if ln["nombre"] == line:
                try:
                    thread = clients.waha_messages(ln, chat_id, limit=config.MSG_LIMIT)
                    for m in thread:
                        if m.get("id"):
                            store.execute(
                                "INSERT OR REPLACE INTO messages(msg_id,chat_id,line,ts,from_me,body,has_media,media_type)"
                                " VALUES(?,?,?,?,?,?,?,?)",
                                (
                                    m["id"],
                                    chat_id,
                                    line,
                                    m.get("timestamp"),
                                    1 if m.get("fromMe") else 0,
                                    m.get("body"),
                                    1 if m.get("hasMedia") else 0,
                                    sync.media_label(m),
                                ),
                            )
                except Exception:  # noqa: BLE001
                    pass
                break
        msgs = store.query(
            "SELECT msg_id,ts,from_me,body,has_media,media_type FROM messages "
            "WHERE chat_id=? AND line=? ORDER BY ts ASC",
            (chat_id, line),
        )
    name = store.query("SELECT name,phone_last4 FROM chats WHERE id=? AND line=?", (chat_id, line))
    return {
        "chat_id": chat_id,
        "line": line,
        "nombre": (name[0]["name"] or f"…{name[0]['phone_last4']}") if name else None,
        "mensajes": [
            {
                "from_me": bool(m["from_me"]),
                "ts": m["ts"],
                "fmt": fmt_full(m["ts"]),
                "body": m["body"],
                "media": m["media_type"] if m["has_media"] else None,
            }
            for m in msgs
        ],
    }


@app.get("/api/envios")
def api_envios():
    hoy = datetime.now(EC)
    dias = []
    for i in range(13, -1, -1):
        d = (hoy - timedelta(days=i)).strftime("%Y-%m-%d")
        dias.append(d)
    series = {ln["nombre"]: {d: 0 for d in dias} for ln in config.lines()}
    recv_series = {ln["nombre"]: {d: 0 for d in dias} for ln in config.lines()}
    inicio = int(datetime.strptime(dias[0], "%Y-%m-%d").replace(tzinfo=EC).timestamp())
    rows = store.query("SELECT line,from_me,ts FROM messages WHERE ts>=?", (inicio,))
    for r in rows:
        d = day_ec(r["ts"])
        if r["from_me"]:
            series.setdefault(r["line"], {}).setdefault(d, 0)
            series[r["line"]][d] = series[r["line"]].get(d, 0) + 1
        else:
            recv_series.setdefault(r["line"], {}).setdefault(d, 0)
            recv_series[r["line"]][d] = recv_series[r["line"]].get(d, 0) + 1

    ultimo = {}
    for ln in config.lines():
        r = store.query(
            "SELECT MAX(last_out_ts) m FROM chats WHERE line=? AND last_out_ts IS NOT NULL", (ln["nombre"],)
        )
        m = r[0]["m"] if r else None
        ultimo[ln["nombre"]] = {"ts": m, "fmt": fmt_full(m)}
    tabla = [
        {
            "fecha": d,
            "por_linea": {ln["nombre"]: series.get(ln["nombre"], {}).get(d, 0) for ln in config.lines()},
            "total": sum(series.get(ln["nombre"], {}).get(d, 0) for ln in config.lines()),
        }
        for d in reversed(dias)
    ]
    return {
        "dias": dias,
        "series": series,
        "respuestas": recv_series,
        "lineas": [ln["nombre"] for ln in config.lines()],
        "ultimo_envio": ultimo,
        "tabla": tabla,
    }


@app.post("/api/lead/{lead_id}/status")
async def api_set_status(lead_id: str, request: Request):
    body = await request.json()
    estado = (body or {}).get("estado")
    if estado not in ESTADOS:
        raise HTTPException(400, "estado inválido")
    try:
        clients.radar_set_status(lead_id, estado)
    except clients.HttpError as e:
        raise HTTPException(502, f"Radar: {e}")
    store.execute("UPDATE leads SET estado=?, updated_at=? WHERE id=?", (estado, store.now(), lead_id))
    return {"ok": True, "lead_id": lead_id, "estado": estado}


@app.post("/api/refresh")
def api_refresh():
    res = sync.refresh()
    return res


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


ARRANCADO_EN = int(time.time())


def _scheduler():
    while True:
        try:
            sync.refresh()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(config.REFRESH_SECONDS)


@app.on_event("startup")
def startup():
    store.connect()
    threading.Thread(target=_scheduler, daemon=True).start()
