"""Configuración del panel a partir de variables de entorno."""
import base64
import json
import os

RADAR_URL = os.environ.get("RADAR_URL", "").rstrip("/")
RADAR_API_TOKEN = os.environ.get("RADAR_API_TOKEN", "")

WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")


def _env_secret(plain_name, b64_name, base_name):
    """El panel de EasyPanel corta un valor en el carácter # (comentario). Para no
    depender de comillas, aceptamos el secreto también en base64."""
    v = os.environ.get(b64_name)
    if v:
        try:
            return base64.b64decode(v).decode("utf-8")
        except Exception:  # noqa: BLE001
            pass
    v = os.environ.get(plain_name) or os.environ.get(base_name, "")
    return v.strip().strip("'\"")


PANEL_USER = _env_secret("PANEL_CAPI_USER", "PANEL_CAPI_USER_B64", "PANEL_USER") or "admin"
PANEL_PASS = _env_secret("PANEL_CAPI_PASS", "PANEL_CAPI_PASS_B64", "PANEL_PASS")

DB_PATH = os.environ.get("DB_PATH", "/data/panel.db")
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "300"))
MSG_LIMIT = int(os.environ.get("MSG_LIMIT", "50"))

# Zona horaria de Ecuador (UTC-5 fijo, sin horario de verano).
TZ_OFFSET = -5 * 3600

_DEFAULT_LINES = [
    {
        "nombre": "principal",
        "host": "https://wahacapi.supercrm.best",
        "session": "joel-envios",
    },
    {
        "nombre": "segunda",
        "host": "https://waha105.supercrm.best",
        "session": "joel-envios-2",
    },
]


def lines():
    raw = os.environ.get("WAHA_LINES", "")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return _DEFAULT_LINES
