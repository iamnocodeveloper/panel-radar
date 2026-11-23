# panel-radar

Panel web de solo lectura para seguir la **prospección por WhatsApp** de Radar de Clientes.
Muestra, leyendo la API de Radar y las dos líneas de WhatsApp (WAHA):

- **Resumen**: enviados y respuestas de hoy por línea, esperando respuesta, tasa de respuesta,
  clientes cerrados y estado de las dos líneas.
- **Kanban**: tarjetas por estado (`nuevo · contactado · respondió · reunión · cliente · descartado`,
  más `sin ficha en Radar` para conversaciones que no cruzan con un prospecto), con cambio de
  estado contra Radar y filtros por línea y zona.
- **Conversaciones**: tabla buscable y el hilo completo de cada chat (texto; el multimedia se
  indica por tipo, no se descarga).
- **Envíos**: envíos por día y por línea de los últimos 14 días, con tabla y hora del último envío.

El panel **no envía ningún mensaje por WhatsApp**: solo lee y permite cambiar el estado de un
lead en Radar.

## Stack

- Backend: FastAPI + Uvicorn (Python 3.12).
- Datos: SQLite persistente en `/data/panel.db` (volumen).
- Refresco en segundo plano cada 5 minutos desde Radar + las dos líneas WAHA. Botón «Actualizar».
- Autenticación básica a nivel de aplicación (todas las rutas, incluida la API).
- Frontend: HTML/CSS/JS vainilla, sin frameworks, sin emojis (SVG inline).

## Variables de entorno

| Variable | Descripción |
|---|---|
| `RADAR_URL` | URL base de Radar de Clientes |
| `RADAR_API_TOKEN` | Token de la API de agente de Radar |
| `WAHA_API_KEY` | Clave de la flota WAHA (header `X-Api-Key`) |
| `PANEL_USER` | Usuario de la autenticación básica |
| `PANEL_PASS` | Contraseña de la autenticación básica |
| `WAHA_LINES` | (opcional) JSON con las líneas; por defecto `principal` y `segunda` |
| `REFRESH_SECONDS` | (opcional) intervalo de refresco, por defecto `300` |

Las credenciales se configuran **solo** como variables de entorno del servicio en EasyPanel.
No se guardan en el repositorio.

## Endpoints internos

- `GET /api/state` — resumen + kanban
- `GET /api/conversations` — tabla de conversaciones (`q`, `line`)
- `GET /api/chat/{line}/{chat_id}` — hilo de una conversación
- `GET /api/envios` — serie de 14 días por línea
- `POST /api/lead/{id}/status` — cambia el estado en Radar (`{"estado": "..."}`)
- `POST /api/refresh` — fuerza un refresco
- `GET /api/health`
