"""Clientes HTTP de Radar y WAHA (stdlib, sin dependencias)."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import config


class HttpError(Exception):
    pass


def _get(url, headers, timeout=40):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return r.status, json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise HttpError(f"HTTP {e.code}: {body}")
    except Exception as e:  # noqa: BLE001
        raise HttpError(str(e))


def _post(url, headers, payload, timeout=40):
    data = json.dumps(payload).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise HttpError(f"HTTP {e.code}: {body}")
    except Exception as e:  # noqa: BLE001
        raise HttpError(str(e))


# ---------------------------------------------------------------- Radar

def radar_headers():
    return {"Authorization": f"Bearer {config.RADAR_API_TOKEN}"}


def radar_today():
    _, data = _get(f"{config.RADAR_URL}/api/agent/today", radar_headers())
    return data


def radar_search(text):
    q = urllib.parse.quote(text)
    _, data = _get(f"{config.RADAR_URL}/api/agent/search?q={q}", radar_headers())
    return data.get("resultados", [])


def radar_set_status(lead_id, estado, nota=None):
    payload = {"estado": estado}
    if nota:
        payload["nota"] = nota
    _, data = _post(
        f"{config.RADAR_URL}/api/agent/lead/{urllib.parse.quote(lead_id)}/status",
        radar_headers(),
        payload,
    )
    return data


# ---------------------------------------------------------------- WAHA

def waha_headers():
    return {"X-Api-Key": config.WAHA_API_KEY}


def waha_session(line):
    _, data = _get(
        f"{line['host']}/api/sessions/{urllib.parse.quote(line['session'])}",
        waha_headers(),
        timeout=20,
    )
    return data


def waha_overview(line, limit=1200):
    _, data = _get(
        f"{line['host']}/api/{urllib.parse.quote(line['session'])}/chats/overview?limit={limit}",
        waha_headers(),
        timeout=60,
    )
    return data


def waha_messages(line, chat_id, limit=None):
    limit = limit or config.MSG_LIMIT
    cid = urllib.parse.quote(chat_id)
    _, data = _get(
        f"{line['host']}/api/{urllib.parse.quote(line['session'])}/chats/{cid}"
        f"/messages?limit={limit}&downloadMedia=false",
        waha_headers(),
        timeout=30,
    )
    return data
