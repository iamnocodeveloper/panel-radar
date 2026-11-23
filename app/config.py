"""Configuración del panel a partir de variables de entorno."""
import json
import os

RADAR_URL = os.environ.get("RADAR_URL", "").rstrip("/")
RADAR_API_TOKEN = os.environ.get("RADAR_API_TOKEN", "")

WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")

PANEL_USER = os.environ.get("PANEL_USER", "admin")
PANEL_PASS = os.environ.get("PANEL_PASS", "")

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
