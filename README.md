# panel-radar

Panel web para seguir la **prospección por WhatsApp** de Radar de Clientes. Lee la API de
Radar y las dos líneas de WhatsApp (WAHA) y muestra:

- **Resumen**: enviados y respuestas de hoy por línea, esperando respuesta, tasa de respuesta,
  clientes cerrados y estado de las dos líneas.
- **Kanban**: nueve columnas `Nuevo · Contactado · Respondió · Interesado · Demo enviado ·
  Cotización enviada · Dijo que luego · Dijo que no · Cliente`. Cada tarjeta muestra el negocio,
  su zona, la línea, si respondió, el estado en Radar, **las tres fechas** (se interesó, demo
  enviado, cotización enviada), el último mensaje con su fecha y la nota. Permite mover el
  cliente a «Interesado / Dijo que luego / Dijo que no», quitar el estado propio («Auto») y
  editar la nota y las fechas a mano. Filtros por línea, zona y texto.
- **Gráficos**: embudo de prospección (nº y % por paso y conversión sobre el paso anterior),
  evolución diaria (7/14/30 días) de enviados y respuestas con línea de tasa, comparativa de
  líneas, envíos y tasa por zona y por rubro, y tasa de respuesta por hora del día y por día
  de la semana. Todo con **SVG/CSS propios, sin librerías ni CDN**. KPIs grandes arriba.
- **Conversaciones**: tabla buscable (línea, zona y texto) y el hilo completo de cada chat
  (texto; el multimedia se indica por tipo, no se descarga).
- **Envíos**: envíos por día y por línea de los últimos 14 días, con tabla y hora del último envío.

El panel **no envía ningún mensaje por WhatsApp**: solo lee, cambia el estado de un lead en
Radar y guarda datos propios del panel.

## Fechas por cliente

Para cada cliente se guardan en la tabla `clientes` (persistente en el volumen):

- **Se interesó**: primer mensaje entrante del cliente en el hilo (deducido de WAHA).
- **Demo enviado**: primer envío nuestro con multimedia (imagen/documento) y un enlace a una
  demo (`easypanel.host`); si no hay enlace, el primer envío de imagen/documento. Si no se puede
  deducir queda «—» y se puede fijar a mano.
- **Cotización enviada**: primer envío nuestro que menciona precios (`$180`, `$400`,
  «cotización», «propuesta»).

Las fechas se deducen al refrescar **solo si el campo está vacío**: lo curado desde fuera o
fijado a mano nunca se pisa.

## Stack

- Backend: FastAPI + Uvicorn (Python 3.12).
- Datos: SQLite persistente en `/data/panel.db` (volumen). Datos propios del panel en la tabla
  `clientes`.
- Refresco en segundo plano cada 5 minutos desde Radar + las dos líneas WAHA. Botón «Actualizar».
- Autenticación básica a nivel de aplicación (todas las rutas, incluida la API), **fail-closed**.
- Frontend: HTML/CSS/JS vainilla, sin frameworks, sin emojis (SVG inline).

## Variables de entorno

| Variable | Descripción |
|---|---|
| `RADAR_URL` | URL base de Radar de Clientes |
| `RADAR_API_TOKEN` | Token de la API de agente de Radar |
| `WAHA_API_KEY` | Clave de la flota WAHA (header `X-Api-Key`) |
| `PANEL_CAPI_USER` / `PANEL_CAPI_USER_B64` | Usuario de la autenticación básica |
| `PANEL_CAPI_PASS` / `PANEL_CAPI_PASS_B64` | Contraseña de la autenticación básica |
| `INGEST_KEY` / `INGEST_KEY_B64` | (opcional) clave del endpoint `POST /api/ingest` |
| `WAHA_LINES` | (opcional) JSON con las líneas; por defecto `principal` y `segunda` |
| `REFRESH_SECONDS` | (opcional) intervalo de refresco, por defecto `300` |

Las credenciales se configuran **solo** como variables de entorno del servicio en EasyPanel.
No se guardan en el repositorio.

La clave de ingesta puede venir por `INGEST_KEY` **o** fijarse con `POST /api/ingest_key`
(misma contraseña del panel): queda en `/data/ingest_key`, en el volumen persistente. Esa vía
existe porque el MCP de EasyPanel enmascara los secretos al leer el env, así que reescribir el
env entero para añadir una variable corrompería las demás.

## Endpoints internos

- `GET /api/state` — resumen + kanban (estados y tarjetas con las tres fechas)
- `GET /api/graficos?dias=7|14|30` — datos de la pestaña de gráficos
- `GET /api/conversations` — tabla de conversaciones (`q`, `line`, `zona`)
- `GET /api/chat/{line}/{chat_id}` — hilo de una conversación
- `GET /api/envios` — serie de 14 días por línea
- `POST /api/cliente/{key}/extra` — estado propio del panel + nota + fechas (`{estado_extra, nota,
  interesado_el, demo_enviado_el, cotizacion_enviada_el}`); solo escribe las claves enviadas
- `POST /api/ingest` — ingesta curada externa, autenticada con cabecera `X-Ingest-Key`
- `POST /api/ingest_key` — fija/rota la clave de ingesta (requiere la contraseña del panel)
- `POST /api/lead/{id}/status` — cambia el estado en Radar (`{"estado": "..."}`)
- `POST /api/refresh` — fuerza un refresco
- `GET /api/health`

### Ingesta curada (`POST /api/ingest`)

Cabecera `X-Ingest-Key: <clave>`. Sin la clave correcta responde **401** (fail-closed).

```json
{"clientes": [
  {"chat": "506...@c.us", "nombre": "...", "interesado_el": "2026-11-23T12:49:00-05:00",
   "demo_enviado_el": "...", "cotizacion_enviada_el": "...",
   "estado_extra": "dijo_que_luego|dijo_que_no|interesado|demo_enviado|cotizacion_enviada|",
   "nota": "texto libre"}
]}
```

Hace *upsert* por `chat` y **nunca borra** lo que ya había si un campo viene vacío. Responde
`{"ok": true, "actualizados": N}`.
