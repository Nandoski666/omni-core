# Merca — Bot WhatsApp Asesor de Ventas IA

Registro del estado del proyecto, decisiones tomadas y qué falta.

---

## Qué es este bot

Bot de WhatsApp para **Merca** (marca de dropshipping — https://merca.me) que atiende clientes que llegan desde anuncios de Facebook/Instagram con click-to-WhatsApp. La IA se llama **Sofía** y actúa como asesora de ventas: saluda, muestra productos, cierra ventas y redirige a merca.me.

Migrado desde el repo original `omni-core` que era un bot de agendamiento de citas con Google Calendar.

---

## Stack

- **Runtime**: Python 3 + FastAPI + uvicorn
- **LLM**: Groq API — modelo `qwen/qwen3.6-27b`
- **Visión**: Groq `meta-llama/llama-4-scout-17b-16e-instruct`
- **Audio (transcripción)**: Groq `whisper-large-v3`
- **Mensajería**: Meta WhatsApp Cloud API v18.0
- **Catálogo de productos**: Google Sheets publicado como CSV
- **Deploy**: Render.com (https://omni-core.onrender.com)
- **Repo**: https://github.com/Nandoski666/omni-core

---

## Estructura de archivos

```
omni-core/
├── main.py         FastAPI app: webhook, HMAC, Groq calls, orquestación
├── catalog.py      Loader de Google Sheets (con cache 5 min)
├── requirements.txt
├── Procfile        web: uvicorn main:app --host 0.0.0.0 --port $PORT
├── .env            (gitignored) credenciales locales
├── .gitignore
└── PROGRESS.md     este archivo
```

---

## Variables de entorno (Render → Environment)

| Variable | Valor / Ejemplo | Notas |
|---|---|---|
| `WHATSAPP_TOKEN` | `EAAM7Uv...` | Bearer token permanente de Meta |
| `PHONE_NUMBER_ID` | `1035105219684137` | ID de 15 dígitos del número (actualmente test number) |
| `WHATSAPP_API_URL` | `https://graph.facebook.com/v18.0` | |
| `WHATSAPP_VERIFY_TOKEN` | `omni_pro_2026` | Debe coincidir con lo configurado en Meta → WhatsApp → Configuration → Webhook |
| `META_APP_SECRET` | `cb1d68572d85da2f7391fef31404cd0a` | Para validar firma HMAC de los webhooks |
| `GROQ_API_KEY` | `gsk_1FvS...` | Cuenta con acceso solo a modelos limitados (ver "Modelos disponibles" abajo) |
| `LLM_MODEL` | (opcional) `qwen/qwen3.6-27b` | Si no se define, usa el default del código |
| `BRAND_NAME` | `Merca` | |
| `SALES_URL` | `https://merca.me` | |
| `CATALOG_CSV_URL` | `https://docs.google.com/spreadsheets/d/1uEhaSoczkBF46PrG0T6tlwarpn7OKTUQDmNUTJdFljM/export?format=csv` | ⚠️ Debe terminar en `/export?format=csv`, NO en `/edit?usp=sharing` |
| `CURRENT_PRODUCT` | (opcional, vacío) | Fallback si no hay catálogo cargado |
| `CURRENT_PRODUCT_ANGLE` | (opcional) | Ángulo del anuncio |

**Reiniciar Render** para que tome cambios: Environment tab → editar → "Save Changes" → redeploy automático (~30-60s).

---

## Catálogo de productos (Google Sheet)

**Sheet actual**: https://docs.google.com/spreadsheets/d/1uEhaSoczkBF46PrG0T6tlwarpn7OKTUQDmNUTJdFljM

### Columnas del sheet (fila 1)

| Nombre | Descripción | Precio | Link | Categoría | Ganador | Activo |

- **Nombre** *(obligatorio)*: nombre del producto
- **Descripción**: beneficio corto (1 línea)
- **Precio**: referencial (el precio real vive en merca.me)
- **Link**: URL directa del producto en merca.me — Sofía usa este link al cerrar la venta
- **Categoría**: para futuros filtros
- **Ganador** = `SI` para productos estrella (Sofía los menciona primero). `NO` o vacío para los demás
- **Activo** = `SI` para que aparezca en el bot. `NO` para pausarlo sin borrarlo. Si la columna no existe, TODOS se consideran activos

### Cómo cambiar productos

1. Abre el Sheet
2. Agrega/edita/quita filas
3. En máximo **5 minutos** (cache TTL) Sofía usa los datos nuevos
4. Sin código, sin redeploy

### Publicar el Sheet como CSV

`Archivo → Compartir → Publicar en la web → Hoja 1 → CSV → Publicar`

O usa el URL directo de export (funciona si el sheet es público):
`https://docs.google.com/spreadsheets/d/<ID>/export?format=csv`

---

## Modelos disponibles en la cuenta Groq actual

Esta cuenta Groq es LIMITADA — solo tiene 13 modelos (no incluye Llama 3/4 populares):

| Modelo | Uso | Estado |
|---|---|---|
| `qwen/qwen3.6-27b` | Chat principal | ✅ Funciona (requiere `reasoning_effort="none"`) |
| `openai/gpt-oss-120b` | Alt chat / visión | ⚠️ Devuelve vacío sin `reasoning_format="hidden"` |
| `openai/gpt-oss-20b` | Alt chat más rápido | ⚠️ Igual que 120b |
| `groq/compound`, `groq/compound-mini` | Sistemas agentic | No probados |
| `meta-llama/llama-4-scout-17b-16e-instruct` | Visión | ✅ Usa este para procesar imágenes |
| `whisper-large-v3` | Audio | ✅ Transcripción |
| `whisper-large-v3-turbo` | Audio (más rápido) | Alternativa |
| `allam-2-7b`, `canopylabs/*` | Otros idiomas | No aplican para español |

**Verificar modelos disponibles** en cualquier momento: abrir `https://omni-core.onrender.com/debug-models`

---

## Endpoints del servicio

| Endpoint | Descripción |
|---|---|
| `GET /` | Status del bot + catálogo cargado |
| `GET /webhook` | Verificación inicial de Meta (challenge) |
| `POST /webhook` | Recibe mensajes de WhatsApp (con validación HMAC) |
| `GET /debug-catalog` | Fuerza recarga del sheet y muestra el fetch crudo |
| `GET /debug-models` | Lista los modelos accesibles con la GROQ_API_KEY actual |

---

## Estado actual del bot

- ✅ Recibe mensajes de WhatsApp
- ✅ Valida firma HMAC de Meta
- ✅ Sofía genera respuestas de venta (con Sofía, prompt en español LATAM)
- ✅ Catálogo dinámico desde Google Sheet (5 min cache)
- ✅ Filtra chain-of-thought de qwen (`<think>...</think>`)
- ✅ Deploy automático en Render al hacer git push
- ⚠️ **Número WhatsApp = Test Number de Meta** — solo responde a 5 números pre-autorizados. Ver "Próximos pasos" para producción real.

---

## Cómo probar

1. Enviar WhatsApp desde tu celular (número que agregaste en Meta como "To"):
   - `hola` → saludo + presenta 2-3 productos estrella con links
   - `cuáles son todos los productos` → lista los 5 productos con links
   - `cuánto vale el teclado el teso` → precio ref + link directo
   - `quiero comprar` → cierra con link específico
   - `quiero hablar con un humano` → escala sin discutir

2. Ver logs en Render → tu servicio → Logs — deben aparecer:
   ```
   📥 Webhook recibido tipo=messages
   🌊 <numero>: <mensaje>
   🧠 Generando respuesta para <numero>...
   🗣️ Sofía: <respuesta>
   📩 Meta status: 200
   ```

---

## Problemas resueltos (historial)

| # | Problema | Solución | Commit |
|---|---|---|---|
| 1 | Bot original era de citas | Reescrito completo a asesor de ventas Sofía | `145c5c1` |
| 2 | Push rechazado (rebase con commits de bot de peluquería preservados en historia) | rebase -X theirs sobre origin/main | `f838d17` |
| 3 | Groq 404 con `llama-3.3-70b-versatile` | Cuenta no tiene ese modelo | (varios) |
| 4 | `gpt-oss-120b` devolvía respuestas vacías | Consume tokens en reasoning; se necesita `reasoning_format="hidden"` | `7460ff7` |
| 5 | Catálogo cargaba 0 productos | User había puesto URL `/edit?usp=sharing` (HTML) en vez de `/export?format=csv` | (config) |
| 6 | Render no auto-deployaba | Manual Deploy → activar Auto-Deploy en Settings | (config) |
| 7 | `qwen` devolvía `<think>...` sin cierre → cliente veía "Hola en qué te ayudo" | `extra_body={"reasoning_effort": "none"}` desactiva thinking | `7460ff7` |
| 8 | Sofía preguntaba "para qué lo usarás" antes de mostrar productos | Prompt refinado: casos A/B/C/D según intención del mensaje | `1f9fd39` |

---

## Próximos pasos (roadmap)

### Corto plazo — pasar a producción real
- [ ] Comprar SIM nueva (SIM aparte, no uso personal)
- [ ] Agregar el número en Meta Business Manager → WhatsApp → Phone Numbers
- [ ] Actualizar `PHONE_NUMBER_ID` en Render con el ID del número nuevo
- [ ] Con esto: hasta **250 conversaciones únicas/día** sin verificación de negocio
- [ ] Para más volumen: completar **Business Verification** en Meta (documentos legales de Merca)

### Mediano plazo — mejoras del bot
- [ ] Persistencia real (PostgreSQL/Redis) — hoy sesiones en RAM se pierden en redeploy
- [ ] Dashboard admin (editar productos, ver conversaciones, cambiar prompts sin código)
- [ ] Escalamiento humano: cuando cliente pida asesor real, notificar a Slack/Telegram
- [ ] Analytics: conversion funnel (mensaje → click merca.me → compra)
- [ ] Plantillas HSM aprobadas por Meta para re-engagement fuera de ventana 24h

### Fase 2 — capacidades avanzadas
- [ ] RAG del catálogo con embeddings (para catálogos grandes >50 productos)
- [ ] Tool calling: `create_order`, `check_stock`, `track_order` — integración con proveedor dropshipping
- [ ] Pagos: validación automática de comprobantes con visión
- [ ] Multi-agente: separar SDR / closer / post-venta
- [ ] A/B testing de prompts

---

## Cómo retomar el proyecto

1. Ver el estado actual: `https://omni-core.onrender.com/`
2. Ver logs en tiempo real: Render dashboard → omni-core → Logs
3. Cambios en código: editar en local, `git add . && git commit && git push` → Render redeploy automático
4. Cambios en productos: editar Google Sheet (5 min de cache)
5. Cambios en config: Render → Environment → Save Changes

---

## Contactos y accesos

- **Repo GitHub**: https://github.com/Nandoski666/omni-core
- **Meta Business**: developers.facebook.com (app "OMNI", ID 909652468620094)
- **Render**: dashboard.render.com (servicio "omni-core")
- **Groq**: console.groq.com (API keys y modelos)
- **Google Sheet catálogo**: https://docs.google.com/spreadsheets/d/1uEhaSoczkBF46PrG0T6tlwarpn7OKTUQDmNUTJdFljM
