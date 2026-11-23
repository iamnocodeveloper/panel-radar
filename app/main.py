"""Panel de prospección Radar + WhatsApp — API FastAPI."""
import base64
import hmac
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import clients, config, store, sync

EC = timezone(timedelta(hours=-5))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Columnas del kanban, en orden. Las de en medio («interesado» en adelante) son
# estados propios del panel que NO existen en Radar y viven en la tabla `clientes`.
ESTADOS = [
    "nuevo",
    "contactado",
    "respondio",
    "interesado",
    "demo_enviado",
    "cotizacion_enviada",
    "dijo_que_luego",
    "dijo_que_no",
    "cliente",
]
# Estados que solo existen en el panel (editables a mano o por ingesta).
PANEL_ESTADOS = ["interesado", "demo_enviado", "cotizacion_enviada", "dijo_que_luego", "dijo_que_no"]
# Para decidir la columna, «más avanzado gana».
RANK = {
    "nuevo": 0,
    "contactado": 1,
    "respondio": 2,
    "interesado": 3,
    "demo_enviado": 4,
    "cotizacion_enviada": 5,
    "cliente": 6,
}
TERMINALES = ("dijo_que_luego", "dijo_que_no")

# Fail-closed: el panel muestra teléfonos de clientes. Si falta la credencial, el
# proceso se niega a arrancar (uvicorn aborta) en vez de servir sin autenticación.
if not (config.PANEL_USER and config.PANEL_PASS):
    raise RuntimeError(
        "Fail-closed: faltan PANEL_CAPI_USER/PANEL_CAPI_PASS. El panel no arranca sin credenciales."
    )

app = FastAPI(title="Panel Radar", docs_url=None, redoc_url=None, openapi_url=None)

ARRANCADO_EN = int(time.time())


# --------------------------------------------------------------- Auth

def _check_auth(request: Request):
    # Fail-closed: sin contraseña configurada el proceso ni siquiera arranca
    # (ver comprobación al principio del módulo). Nunca se deja pasar sin auth.
    if not config.PANEL_PASS:
        return False
    hdr = request.headers.get("authorization", "")
    if not hdr.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(hdr.split(" ", 1)[1]).decode("utf-8", "replace")
        user, _, pw = raw.partition(":")
    except Exception:  # noqa: BLE001
        return False
    return hmac.compare_digest(user, config.PANEL_USER) and hmac.compare_digest(pw, config.PANEL_PASS)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # /api/ingest se protege con su propia cabecera X-Ingest-Key (fail-closed en el
    # propio endpoint), no con la contraseña del panel: así un cron externo puede
    # empujar datos curados sin tener las credenciales del panel.
    if request.url.path != "/api/ingest" and not _check_auth(request):
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


def fmt_fecha(v):
    """Formatea una fecha ISO (con o sin hora) curada o deducida."""
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except Exception:  # noqa: BLE001
        return v
    return dt.strftime("%d/%m %H:%M") if "T" in v else dt.strftime("%d/%m/%Y")


def day_ec(ts):
    return datetime.fromtimestamp(int(ts), EC).strftime("%Y-%m-%d")


def today_ec():
    return datetime.now(EC).strftime("%Y-%m-%d")


def trunc(s, n=120):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


RADAR_ESTADOS = ["nuevo", "contactado", "respondio", "reunion", "cliente", "descartado"]


def effective_col(radar_estado, responded, cli):
    """Columna efectiva del kanban combinando Radar, fechas y estado propio del panel."""
    cli = cli or {}
    extra = cli.get("estado_extra") or ""
    if radar_estado == "cliente":
        return "cliente"
    if extra in TERMINALES:
        return extra
    if radar_estado == "descartado":
        return "dijo_que_no"
    base = {
        "nuevo": "nuevo",
        "contactado": "respondio" if responded else "contactado",
        "respondio": "respondio",
        "reunion": "interesado",
    }.get(radar_estado, "nuevo")
    cands = [base]
    if cli.get("demo_enviado_el"):
        cands.append("demo_enviado")
    if cli.get("cotizacion_enviada_el"):
        cands.append("cotizacion_enviada")
    if extra in ("interesado", "demo_enviado", "cotizacion_enviada"):
        cands.append(extra)
    return max(cands, key=lambda k: RANK.get(k, 0))


def _merge_clientes(rows):
    """Fusiona filas de `clientes` de varias claves (varias líneas de un lead)."""
    rows = [r for r in rows if r]
    if not rows:
        return {}
    rows.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)

    def first(f):
        for r in rows:
            if r.get(f) not in (None, ""):
                return r[f]
        return None

    def earliest(f):
        vals = [r[f] for r in rows if r.get(f) not in (None, "")]
        return min(vals) if vals else None

    return {
        "estado_extra": first("estado_extra"),
        "nota": first("nota"),
        "nombre": first("nombre"),
        "interesado_el": earliest("interesado_el"),
        "demo_enviado_el": earliest("demo_enviado_el"),
        "cotizacion_enviada_el": earliest("cotizacion_enviada_el"),
    }


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
        "chat_id": ch["id"],
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


def _cliente_embed(cli):
    cli = cli or {}
    return {
        "interesado_el": cli.get("interesado_el"),
        "interesado_fmt": fmt_fecha(cli.get("interesado_el")),
        "demo_enviado_el": cli.get("demo_enviado_el"),
        "demo_fmt": fmt_fecha(cli.get("demo_enviado_el")),
        "cotizacion_enviada_el": cli.get("cotizacion_enviada_el"),
        "cotizacion_fmt": fmt_fecha(cli.get("cotizacion_enviada_el")),
        "estado_extra": cli.get("estado_extra"),
        "nota": cli.get("nota"),
    }


def build_kanban():
    chats = store.query("SELECT * FROM chats WHERE is_prospect=1 OR lead_id IS NOT NULL")
    allc = store.cliente_all()
    by_lead = {}
    unmatched = []
    for ch in chats:
        if ch.get("lead_id"):
            by_lead.setdefault(ch["lead_id"], []).append(ch)
        elif ch.get("is_prospect"):
            unmatched.append(ch)

    zones = set()
    cards = []
    for l in store.query("SELECT * FROM leads"):
        lead_chats = sorted(by_lead.get(l["id"], []), key=lambda c: c.get("last_ts") or 0, reverse=True)
        rep = lead_chats[0] if lead_chats else None
        responded = any(c.get("responded") for c in lead_chats)
        rows = [allc.get(c["id"]) for c in lead_chats] + [allc.get(f"lead:{l['id']}")]
        cli = _merge_clientes(rows)
        # clave editable: el chat que ya tenga datos propios, o el más reciente, o el lead
        ckey = next((c["id"] for c in lead_chats if allc.get(c["id"])), None)
        ckey = ckey or (rep["id"] if rep else f"lead:{l['id']}")
        zones.add(l.get("zona") or "—")
        radar_estado = l.get("estado") or "nuevo"
        card = {
            "key": f"lead:{l['id']}",
            "cliente_key": ckey,
            "lead_id": l["id"],
            "nombre": cli.get("nombre") or l.get("nombre"),
            "zona": l.get("zona"),
            "tipo": l.get("tipo"),
            "estado": effective_col(radar_estado, responded, cli),
            "radar_estado": radar_estado,
            "mensajes_enviados": l.get("mensajes_enviados"),
            "conversacion": _chat_embed(rep) if rep else None,
        }
        card.update(_cliente_embed(cli))
        cards.append(card)

    for ch in unmatched:
        cli = allc.get(ch["id"]) or {}
        zones.add("—")
        card = {
            "key": f"chat:{ch['line']}:{ch['id']}",
            "cliente_key": ch["id"],
            "lead_id": None,
            "nombre": cli.get("nombre") or ch.get("name") or f"…{ch['phone_last4']}",
            "zona": None,
            "tipo": None,
            "estado": effective_col("contactado", ch.get("responded"), cli),
            "radar_estado": None,
            "mensajes_enviados": None,
            "conversacion": _chat_embed(ch),
        }
        card.update(_cliente_embed(cli))
        cards.append(card)

    cards.sort(key=lambda c: (-(((c["conversacion"] or {}).get("ultimo_ts") or 0)), (c["nombre"] or "").lower()))

    counts = {e: 0 for e in ESTADOS}
    for c in cards:
        counts[c["estado"]] = counts.get(c["estado"], 0) + 1

    return {"cards": cards, "counts": counts, "zonas": sorted(z for z in zones if z)}


# --------------------------------------------------------------- gráficos

DIASEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def build_graficos(dias=30):
    dias = dias if dias in (7, 14, 30) else 30
    cards = build_kanban()["cards"]
    leads = {l["id"]: l for l in store.query("SELECT id,zona,tipo FROM leads")}
    chat_meta = {}
    for ch in store.query("SELECT id,line,lead_id FROM chats"):
        lead = leads.get(ch.get("lead_id"))
        chat_meta[(ch["id"], ch["line"])] = (
            (lead.get("zona") if lead else None),
            (lead.get("tipo") if lead else None),
        )

    # --- embudo (por cliente, acumulativo: quien llegó a un paso pasó por los anteriores)
    fun = {"enviados": 0, "respondidos": 0, "interesados": 0, "demo": 0, "cotizacion": 0, "cliente": 0}
    for c in cards:
        cv = c.get("conversacion") or {}
        contacted = bool(cv.get("sent")) or (c.get("mensajes_enviados") or 0) > 0
        if not contacted:
            continue
        fun["enviados"] += 1
        est = c["estado"]
        if cv.get("responded"):
            fun["respondidos"] += 1
        if est == "interesado" or c.get("estado_extra") == "interesado" or RANK.get(est, 0) >= 3:
            fun["interesados"] += 1
        if c.get("demo_enviado_el") or RANK.get(est, 0) >= 4:
            fun["demo"] += 1
        if c.get("cotizacion_enviada_el") or RANK.get(est, 0) >= 5:
            fun["cotizacion"] += 1
        if c.get("radar_estado") == "cliente" or est == "cliente":
            fun["cliente"] += 1

    pasos = [
        ("Enviados", fun["enviados"]),
        ("Respondidos", fun["respondidos"]),
        ("Interesados", fun["interesados"]),
        ("Demo enviado", fun["demo"]),
        ("Cotización enviada", fun["cotizacion"]),
        ("Cliente", fun["cliente"]),
    ]
    total = pasos[0][1]
    embudo = []
    prev = None
    for name, n in pasos:
        embudo.append(
            {
                "paso": name,
                "n": n,
                "pct_total": _pct(n, total),
                "pct_prev": None if prev is None else _pct(n, prev),
            }
        )
        prev = n

    # --- ventana temporal
    ahora = datetime.now(EC)
    hoy0 = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    dias_lista = [(hoy0 - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias - 1, -1, -1)]
    inicio = int((hoy0 - timedelta(days=dias - 1)).timestamp())
    rango30 = int((hoy0 - timedelta(days=29)).timestamp())
    desde = min(inicio, rango30)

    msgs = store.query("SELECT chat_id,line,from_me,ts FROM messages WHERE ts>=?", (desde,))

    env_dia = {d: 0 for d in dias_lista}
    rec_dia = {d: 0 for d in dias_lista}
    env_hora = {i: 0 for i in range(12)}  # bloques de 2 h (últimos 30 días)
    rec_hora = {i: 0 for i in range(12)}
    env_dow = {d: 0 for d in range(7)}
    rec_dow = {d: 0 for d in range(7)}
    env_linea = {ln["nombre"]: 0 for ln in config.lines()}
    rec_linea = {ln["nombre"]: 0 for ln in config.lines()}
    zona_stat = {}
    tipo_stat = {}

    for m in msgs:
        ts = m["ts"]
        if ts >= inicio:
            d = day_ec(ts)
            if d in env_dia:
                (env_dia if m["from_me"] else rec_dia)[d] += 1
        if ts >= rango30:
            dt = datetime.fromtimestamp(ts, EC)
            hb = dt.hour // 2
            (env_hora if m["from_me"] else rec_hora)[hb] += 1
            dw = dt.weekday()
            (env_dow if m["from_me"] else rec_dow)[dw] += 1
            if m["from_me"]:
                env_linea[m["line"]] = env_linea.get(m["line"], 0) + 1
            else:
                rec_linea[m["line"]] = rec_linea.get(m["line"], 0) + 1
            zona, tipo = chat_meta.get((m["chat_id"], m["line"]), (None, None))
            if zona:
                z = zona_stat.setdefault(zona, [0, 0])
                z[0 if m["from_me"] else 1] += 1
            if tipo:
                t = tipo_stat.setdefault(tipo, [0, 0])
                t[0 if m["from_me"] else 1] += 1

    diaria = {
        "dias": dias_lista,
        "enviados": [env_dia[d] for d in dias_lista],
        "respuestas": [rec_dia[d] for d in dias_lista],
        "tasa": [_pct(rec_dia[d], env_dia[d]) for d in dias_lista],
    }

    lineas = [
        {
            "line": ln["nombre"],
            "enviados": env_linea.get(ln["nombre"], 0),
            "respuestas": rec_linea.get(ln["nombre"], 0),
            "tasa": _pct(rec_linea.get(ln["nombre"], 0), env_linea.get(ln["nombre"], 0)),
        }
        for ln in config.lines()
    ]

    def _stat(mapping, keyname):
        out = []
        for k, (e, r) in mapping.items():
            out.append({keyname: k, "enviados": e, "respuestas": r, "tasa": _pct(r, e)})
        out.sort(key=lambda x: -x["enviados"])
        return out

    zonas = _stat(zona_stat, "zona")
    rubros = _stat(tipo_stat, "tipo")

    horas = [
        {
            "bloque": f"{i * 2:02d}-{i * 2 + 2:02d}",
            "enviados": env_hora[i],
            "respuestas": rec_hora[i],
            "tasa": _pct(rec_hora[i], env_hora[i]),
        }
        for i in range(12)
    ]
    diasemana = [
        {
            "dia": DIASEMANA[i],
            "enviados": env_dow[i],
            "respuestas": rec_dow[i],
            "tasa": _pct(rec_dow[i], env_dow[i]),
        }
        for i in range(7)
    ]

    env_total = sum(env_linea.values())
    rec_total = sum(rec_linea.values())
    return {
        "dias": dias,
        "kpis": {
            "enviados": env_total,
            "respuestas": rec_total,
            "tasa": _pct(rec_total, env_total),
            "interesados": fun["interesados"],
            "demos": fun["demo"],
            "cotizaciones": fun["cotizacion"],
            "clientes": fun["cliente"],
        },
        "embudo": embudo,
        "diaria": diaria,
        "lineas": lineas,
        "zonas": zonas,
        "rubros": rubros,
        "horas": horas,
        "diasemana": diasemana,
    }


# --------------------------------------------------------------- rutas

@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "last_refresh": store.get_meta("last_refresh"),
        "version": "1.2.0",
        "auth_configurada": bool(config.PANEL_PASS),
        "ingest_configurada": bool(config.ingest_key()),
        "arrancado_en": ARRANCADO_EN,
    }


@app.get("/api/state")
def api_state():
    return {
        "resumen": build_resumen(),
        "kanban": build_kanban(),
        "estados": ESTADOS,
        "last_refresh": store.get_meta("last_refresh"),
        "last_refresh_fmt": fmt_dt(store.get_meta("last_refresh")),
        "last_error": store.get_meta("last_error"),
        "refreshing": store.get_meta("refreshing") == "1",
    }


@app.get("/api/graficos")
def api_graficos(dias: int = 30):
    return build_graficos(dias)


@app.get("/api/conversations")
def api_conversations(q: str = "", line: str = "", zona: str = ""):
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
            l = store.query("SELECT nombre,estado,zona,tipo FROM leads WHERE id=?", (ch["lead_id"],))
            lead = l[0] if l else None
        cli = store.cliente_get(ch["id"]) or {}
        radar_estado = (lead["estado"] if lead else None) or "contactado"
        item = {
            "chat_id": ch["id"],
            "line": ch["line"],
            "nombre": cli.get("nombre") or ch.get("name") or f"…{ch['phone_last4']}",
            "phone_last4": ch["phone_last4"],
            "estado": effective_col(radar_estado, ch.get("responded"), cli),
            "lead_nombre": lead["nombre"] if lead else None,
            "zona": lead["zona"] if lead else None,
            "tipo": lead["tipo"] if lead else None,
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
    if zona:
        out = [it for it in out if (it.get("zona") or "—") == zona]
    if q:
        ql = sync.norm(q)
        out = [
            it
            for it in out
            if ql in sync.norm(it["nombre"])
            or ql in sync.norm(it.get("lead_nombre") or "")
            or ql in sync.norm(it.get("zona") or "")
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
    if estado not in RADAR_ESTADOS:
        raise HTTPException(400, "estado inválido")
    try:
        clients.radar_set_status(lead_id, estado)
    except clients.HttpError as e:
        raise HTTPException(502, f"Radar: {e}")
    store.execute("UPDATE leads SET estado=?, updated_at=? WHERE id=?", (estado, store.now(), lead_id))
    return {"ok": True, "lead_id": lead_id, "estado": estado}


@app.post("/api/cliente/{key}/extra")
async def api_cliente_extra(key: str, request: Request):
    """Edición manual del estado propio del panel y de la nota / fechas del cliente.

    Es información del panel (no escribe en Radar). Solo escribe las claves
    presentes en el cuerpo, así que una cadena vacía sirve para vaciar.
    """
    body = await request.json()
    body = body or {}
    vals = {}
    if "estado_extra" in body:
        ee = (body.get("estado_extra") or "").strip()
        if ee and ee not in PANEL_ESTADOS:
            raise HTTPException(400, "estado inválido")
        vals["estado_extra"] = ee
    if "nota" in body:
        vals["nota"] = (body.get("nota") or "").strip()[:500]
    for f in ("interesado_el", "demo_enviado_el", "cotizacion_enviada_el"):
        if f in body:
            vals[f] = (body.get(f) or "").strip()[:40]
    if not vals:
        raise HTTPException(400, "nada que actualizar")
    store.cliente_set(key, vals)
    cli = store.cliente_get(key) or {}
    return {"ok": True, "cliente": {**_cliente_embed(cli), "cliente_key": key}}


@app.post("/api/ingest")
async def api_ingest(request: Request):
    """Ingesta curada desde fuera (cron de este host). Autenticada con X-Ingest-Key.

    Hace upsert por `chat` y NUNCA borra lo que ya había si un campo viene vacío.
    """
    key = config.ingest_key() or ""
    got = request.headers.get("x-ingest-key", "")
    if not key or not got or not hmac.compare_digest(got, key):
        return JSONResponse({"ok": False, "error": "no autorizado"}, status_code=401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "JSON inválido")
    items = (body or {}).get("clientes") or []
    actualizados = 0
    for it in items:
        it = it or {}
        chat = it.get("chat")
        if not chat:
            continue
        ee = (it.get("estado_extra") or "").strip()
        if ee and ee not in PANEL_ESTADOS:
            ee = ""  # valor desconocido: se ignora (no pisa lo que había)
        vals = {
            "nombre": (it.get("nombre") or "").strip() or None,
            "interesado_el": (it.get("interesado_el") or "").strip() or None,
            "demo_enviado_el": (it.get("demo_enviado_el") or "").strip() or None,
            "cotizacion_enviada_el": (it.get("cotizacion_enviada_el") or "").strip() or None,
            "estado_extra": ee or None,
            "nota": (it.get("nota") or "").strip() or None,
        }
        store.cliente_upsert(chat, vals, overwrite=True)
        actualizados += 1
    return {"ok": True, "actualizados": actualizados}


@app.post("/api/ingest_key")
async def api_set_ingest_key(request: Request):
    """Fija o rota la clave del endpoint de ingesta (misma contraseña del panel).

    Permite provisionar la clave sin reescribir el env del servicio (el MCP de EasyPanel
    enmascara los secretos, así que un updateAppEnv los corrompería). La clave queda en el
    volumen persistente y sobrevive a los redeploys.
    """
    body = await request.json()
    key = ((body or {}).get("key") or "").strip()
    if len(key) < 16:
        raise HTTPException(400, "la clave debe tener al menos 16 caracteres")
    config.write_ingest_key(key)
    return {"ok": True, "ingest_configurada": True}


@app.post("/api/refresh")
def api_refresh():
    return sync.refresh()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
