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

# Clave del endpoint de ingesta curada (POST /api/ingest). No es la contraseña del
# panel: permite empujar desde fuera «a este le enviamos el demo el día X». Si falta,
# el endpoint responde 401 (fail-closed). Se acepta también en base64 por el corte del #.
INGEST_KEY = _env_secret("INGEST_KEY", "INGEST_KEY_B64", "PANEL_INGEST_KEY")
# Ruta del fichero donde se persiste la clave si no viene por variable de entorno. Vive
# en el volumen persistente para sobrevivir a los redeploys. Se puede fijar/rotar por
# POST /api/ingest_key (misma contraseña del panel) sin tocar el env del servicio.
INGEST_KEY_PATH = os.environ.get(
    "INGEST_KEY_PATH", os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/panel.db")), "ingest_key")
)


def _read_ingest_file():
    try:
        with open(INGEST_KEY_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def ingest_key():
    """Clave vigente del endpoint de ingesta: variable de entorno o fichero del volumen."""
    return _env_secret("INGEST_KEY", "INGEST_KEY_B64", "PANEL_INGEST_KEY") or _read_ingest_file()


def write_ingest_key(key):
    os.makedirs(os.path.dirname(INGEST_KEY_PATH) or ".", exist_ok=True)
    with open(INGEST_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(INGEST_KEY_PATH, 0o600)
    except Exception:  # noqa: BLE001
        pass

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
