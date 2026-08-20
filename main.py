import os
import hmac
import hashlib
import json
import time
import asyncio
import base64
import io

import re

import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq
from dotenv import load_dotenv

import catalog

THINK_TAGS_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
THINK_LEADING_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)

# --- ENV ---
load_dotenv()

app = FastAPI(title="Merca - WhatsApp Sales Bot")

# --- CONFIGURACIÓN ---
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "omni_pro_2026")
META_APP_SECRET = os.getenv("META_APP_SECRET")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v18.0")

BRAND_NAME = os.getenv("BRAND_NAME", "Merca")
SALES_URL = os.getenv("SALES_URL", "https://merca.me")
CURRENT_PRODUCT = os.getenv("CURRENT_PRODUCT", "").strip()
CURRENT_PRODUCT_ANGLE = os.getenv("CURRENT_PRODUCT_ANGLE", "").strip()

LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.6-27b")
VISION_MODEL = os.getenv("VISION_MODEL", "openai/gpt-oss-120b")
FALLBACK_VISION_MODEL = os.getenv("FALLBACK_VISION_MODEL", "openai/gpt-oss-20b")
AUDIO_MODEL = os.getenv("AUDIO_MODEL", "whisper-large-v3")

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_HOURS", "24")) * 3600
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

# --- CATÁLOGO (Google Sheet publicado como CSV) ---
CATALOG_CSV_URL = os.getenv("CATALOG_CSV_URL", "").strip()
CATALOG_CACHE_SECONDS = int(os.getenv("CATALOG_CACHE_MINUTES", "5")) * 60

# --- MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GROQ CLIENT ---
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

# --- MEMORIA RAM POR NÚMERO ---
# {phone: {"messages": [...], "updated": ts}}
active_sessions: dict[str, dict] = {}

# --- SYSTEM PROMPT: ASESOR DE VENTAS ---
SYSTEM_PROMPT_TEMPLATE = """Eres "Sofía", asesora de ventas senior de {BRAND_NAME} ({SALES_URL}). Escribes por WhatsApp a clientes que llegaron desde un anuncio de Facebook/Instagram.

MISIÓN: hacer sentir escuchado al cliente, resolver dudas y guiarlo a comprar el producto correcto en {SALES_URL}.

TONO Y ESTILO:
- Humana, cálida, cercana. 1-2 emojis por mensaje MÁXIMO.
- Mensajes CORTOS estilo WhatsApp: 2-4 líneas, máximo 50 palabras.
- Español neutro LATAM, tuteo.
- Nunca digas que eres IA, bot ni asistente virtual. Si preguntan directamente: "soy parte del equipo de {BRAND_NAME}".

CÓMO ATENDER SEGÚN LO QUE PREGUNTE EL CLIENTE:

CASO A — Pregunta directa por productos ("¿qué tienen?", "muéstrame el catálogo", "qué venden"):
→ Lista de UNA vez 3-5 productos del catálogo (prioriza los estrella). Formato:
   "Estos son algunos de nuestros favoritos 💜
   • [Nombre] — [beneficio corto] → [link]
   • [Nombre] — [beneficio corto] → [link]
   ¿Alguno te llama la atención?"
→ NO preguntes "para qué lo quieres" ANTES de mostrarlos. Muéstralos y AL FINAL preguntas cuál le interesa.

CASO B — Pregunta por un producto específico ("cuánto vale X?", "tienen el reloj?"):
→ Responde DIRECTO con el nombre, precio y link de ese producto. Ejemplo:
   "Sí, tenemos el [Nombre] a [precio ref] 🔥
   Aquí lo puedes ver y comprar: [link]
   ¿Te lo despacho a algún lado en particular?"
→ NO preguntes "para qué lo vas a usar" o "cuál prefieres" — el cliente ya sabe qué quiere.

CASO C — Mensaje vago sin pedir nada ("hola", "info"):
→ Saluda cálido + presenta 2-3 productos estrella con sus links.
→ Ejemplo: "¡Hola! 💜 Bienvenido a {BRAND_NAME}. Hoy están arrasando: • [Producto 1] → [link] • [Producto 2] → [link]. ¿Cuál te llama más la atención?"

CASO D — Cliente indeciso o pide recomendación ("no sé cuál elegir", "recomiéndame"):
→ AHÍ SÍ pregunta 1 cosa para orientar (uso principal, presupuesto, o para quién es). Solo UNA pregunta.
→ Luego recomienda el producto que encaje con su respuesta.

MANEJO DE OBJECIONES: Precio → valor y facilidad de compra. Duda → seguridad. Tiempo → invita a ver detalles sin presión.

CIERRE: cuando muestre interés real ("quiero uno", "cómo compro"), envía el link específico del producto y confirma. "Perfecto, aquí lo compras en 2 minutos 👉 [link del producto]. Cuéntame cuando lo abras 💜"
{CATALOG_BLOCK}
REGLAS ESTRICTAS (NO NEGOCIABLES):
- Si el cliente se enoja, insulta, pide reembolso, reporta un pedido con problema, o pide hablar con un humano: responde "Entiendo, voy a pasar tu caso a un asesor humano ahora mismo para que te atienda personalmente 🙏" y NO intentes resolverlo tú.
- Si envían foto de un producto ("quiero algo así"), confirma qué viste y sugiere el producto del catálogo que más se parece con su link.
- Nunca hables de temas ajenos a {BRAND_NAME}.
- Un mensaje = una idea. No listes 5 preguntas juntas.
"""


def build_system_prompt() -> str:
    catalog_block = catalog.get_formatted_for_prompt()
    if not catalog_block:
        # Fallback si aún no hay catálogo: usa CURRENT_PRODUCT si existe
        product = CURRENT_PRODUCT or "nuestros productos destacados"
        angle = CURRENT_PRODUCT_ANGLE or "productos seleccionados con mucho cuidado"
        catalog_block = (
            f"\nPRODUCTO PROMOCIONADO ACTUALMENTE: {product} — {angle}\n"
            f"Redirige siempre a {SALES_URL} para precios y detalles actualizados.\n"
            "REGLA: no inventes precios ni stock específicos.\n"
        )
    return SYSTEM_PROMPT_TEMPLATE.format(
        BRAND_NAME=BRAND_NAME,
        SALES_URL=SALES_URL,
        CATALOG_BLOCK=catalog_block,
    )


def _session_valid(session: dict) -> bool:
    return time.time() - session.get("updated", 0) <= SESSION_TTL_SECONDS


def append_to_session(phone: str, message: dict) -> list[dict]:
    system_prompt = build_system_prompt()
    session = active_sessions.get(phone)
    if not session or not _session_valid(session):
        session = {"messages": [{"role": "system", "content": system_prompt}], "updated": time.time()}
    session["messages"].append(message)
    if len(session["messages"]) > MAX_HISTORY_MESSAGES:
        session["messages"] = [session["messages"][0]] + session["messages"][-(MAX_HISTORY_MESSAGES - 1):]
    session["updated"] = time.time()
    active_sessions[phone] = session
    return session["messages"]


# --- FUNCIONES DE MENSAJERÍA ---

async def send_whatsapp_message(to_phone: str, text: str) -> None:
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=15) as http_client:
        response = await http_client.post(url, json=payload, headers=headers)
        print(f"📩 Meta status: {response.status_code}")
        if response.status_code != 200:
            print(f"⚠️ Meta error: {response.text}")


async def download_whatsapp_media(media_id: str) -> bytes | None:
    url = f"{WHATSAPP_API_URL}/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=30) as http_client:
        meta_resp = await http_client.get(url, headers=headers)
        if meta_resp.status_code != 200:
            print(f"❌ Media URL fetch failed: {meta_resp.text}")
            return None
        media_url = meta_resp.json().get("url")
        if not media_url:
            return None
        binary_resp = await http_client.get(media_url, headers=headers)
        if binary_resp.status_code != 200:
            print(f"❌ Media binary download failed: {binary_resp.text}")
            return None
        return binary_resp.content


async def analyze_image_with_vision(image_bytes: bytes) -> str:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        f"Un cliente de {BRAND_NAME} envió esta imagen por WhatsApp. "
        "Describe brevemente qué muestra: si es un producto que le gusta, "
        "un comprobante de pago, una captura de otra tienda, o algo más. "
        "Sé conciso y directo (máx 3 líneas)."
    )

    async def call_model(model_id: str):
        return await client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                }
            ],
            max_tokens=250,
        )

    try:
        response = await call_model(VISION_MODEL)
    except Exception as e:
        print(f"⚠️ {VISION_MODEL} falló ({e}), usando fallback...")
        response = await call_model(FALLBACK_VISION_MODEL)
    return response.choices[0].message.content


async def transcribe_audio(audio_bytes: bytes) -> str | None:
    try:
        audio_file = io.BytesIO(audio_bytes)
        transcription = await client.audio.transcriptions.create(
            file=("voice_note.ogg", audio_file),
            model=AUDIO_MODEL,
            response_format="text",
        )
        return transcription
    except Exception as e:
        print(f"❌ Groq Whisper error: {e}")
        return None


# --- IA: RESPUESTA DE SOFÍA ---

def _strip_thinking(text: str) -> str:
    """Elimina chain-of-thought de modelos qwen/deepseek en cualquier forma."""
    # 1. Bloques cerrados <think>...</think>
    out = THINK_TAGS_RE.sub("", text)
    # 2. Si sigue habiendo </think> al inicio (respuesta empieza con cierre solamente)
    if "</think>" in out.lower():
        out = THINK_LEADING_RE.sub("", out, count=1)
    # 3. Bloques abiertos sin cierre (<think> sin </think> — se corta a mitad)
    out = THINK_UNCLOSED_RE.sub("", out)
    return out.strip()


async def get_sales_response(phone: str, user_text: str) -> str:
    # Convención qwen: sufijo /no_think fuerza respuesta directa
    user_message_for_llm = f"{user_text} /no_think"
    messages = append_to_session(phone, {"role": "user", "content": user_message_for_llm})
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=1200,
            temperature=0.6,
        )
        msg = response.choices[0].message
        raw = (getattr(msg, "content", "") or "").strip()
        cleaned = _strip_thinking(raw)
        if not cleaned:
            reasoning = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
            print(f"⚠️ content vacío tras strip. raw={raw[:200]} reasoning={str(reasoning)[:200]}", flush=True)
            cleaned = _strip_thinking(str(reasoning or "")) or "¡Hola! 💜 ¿En qué te ayudo?"
        answer = cleaned
    except Exception as e:
        print(f"❌ Groq error: {e}", flush=True)
        answer = "Perdona, tuve un problemita técnico 🙏 ¿Me repites en un momento?"
    # Guarda en historial el mensaje SIN el sufijo /no_think (para conversación limpia)
    append_to_session(phone, {"role": "assistant", "content": answer})
    return answer


# --- ENDPOINTS ---

@app.get("/")
async def home():
    await catalog.refresh_if_stale(CATALOG_CSV_URL, CATALOG_CACHE_SECONDS, SALES_URL)
    products = catalog.get_products()
    return {
        "status": "online",
        "brand": BRAND_NAME,
        "sales_url": SALES_URL,
        "catalog_configured": bool(CATALOG_CSV_URL),
        "catalog_url_hint": CATALOG_CSV_URL[:60] + "..." if len(CATALOG_CSV_URL) > 60 else CATALOG_CSV_URL,
        "products_loaded": len(products),
        "products_names": [p["nombre"] for p in products],
        "current_product_fallback": CURRENT_PRODUCT or "(sin fallback)",
    }


@app.get("/debug-models")
async def debug_models():
    """Lista los modelos disponibles con la GROQ_API_KEY actual."""
    try:
        async with httpx.AsyncClient(timeout=10) as http_client:
            r = await http_client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"},
            )
            data = r.json()
            models = [m.get("id") for m in data.get("data", [])]
            return {
                "http_status": r.status_code,
                "total_models": len(models),
                "models": sorted(models),
                "current_llm_model_setting": LLM_MODEL,
            }
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug-catalog")
async def debug_catalog():
    """Fuerza una recarga del catálogo y devuelve el detalle crudo del fetch."""
    import time as _t
    if not CATALOG_CSV_URL:
        return {"error": "CATALOG_CSV_URL no está configurado"}
    result = {"url_used": CATALOG_CSV_URL}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http_client:
            r = await http_client.get(CATALOG_CSV_URL)
            result["http_status"] = r.status_code
            result["content_type"] = r.headers.get("content-type", "")
            result["first_500_chars"] = r.text[:500]
            result["total_bytes"] = len(r.text)
    except Exception as e:
        result["fetch_error"] = str(e)
        return result
    # Force refresh
    catalog._last_refresh_ts = 0
    await catalog.refresh_if_stale(CATALOG_CSV_URL, CATALOG_CACHE_SECONDS, SALES_URL)
    result["products_after_refresh"] = [p["nombre"] for p in catalog.get_products()]
    return result


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print("✅ WEBHOOK_VERIFIED")
        return Response(content=challenge, media_type="text/plain")

    return Response(content="Token invalido", status_code=403)


@app.post("/webhook")
async def receive_whatsapp(request: Request, x_hub_signature_256: str = Header(None)):
    body_bytes = await request.body()

    # Seguridad HMAC SHA-256
    if META_APP_SECRET and x_hub_signature_256:
        expected = hmac.new(META_APP_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        if f"sha256={expected}" != x_hub_signature_256:
            print("❌ Firma inválida")
            raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        print(f"❌ JSON inválido: {e}", flush=True)
        return {"status": "invalid_json"}

    # Log resumido de qué llegó (para diagnóstico)
    try:
        _v = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        _kind = "messages" if "messages" in _v else ("statuses" if "statuses" in _v else "other")
        print(f"📥 Webhook recibido tipo={_kind}", flush=True)
    except Exception:
        print("📥 Webhook recibido (estructura inesperada)", flush=True)

    # Responder rápido a Meta y procesar en background
    asyncio.create_task(catalog.refresh_if_stale(CATALOG_CSV_URL, CATALOG_CACHE_SECONDS, SALES_URL))
    asyncio.create_task(_handle_event(data))
    return {"status": "received"}


async def _handle_event(data: dict) -> None:
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        if "messages" not in value:
            print("ℹ️ Webhook sin 'messages' (probablemente status update)")
            return

        message = value["messages"][0]
        phone_number = message["from"]
        msg_type = message.get("type")

        user_text = ""

        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            print(f"🌊 {phone_number}: {user_text}", flush=True)

        elif msg_type == "image":
            image_data = message.get("image", {})
            media_id = image_data.get("id")
            caption = image_data.get("caption", "")
            print(f"📸 Imagen de {phone_number} (id={media_id})")
            image_bytes = await download_whatsapp_media(media_id)
            if image_bytes:
                analysis = await analyze_image_with_vision(image_bytes)
                user_text = f"[EL CLIENTE ENVIÓ UNA IMAGEN] Descripción: {analysis}"
                if caption:
                    user_text += f"\nComentario del cliente: {caption}"
            else:
                user_text = "El cliente envió una imagen pero no se pudo descargar."

        elif msg_type == "audio":
            audio_data = message.get("audio", {})
            media_id = audio_data.get("id")
            print(f"🎙️ Audio de {phone_number} (id={media_id})")
            audio_bytes = await download_whatsapp_media(media_id)
            if audio_bytes:
                transcription = await transcribe_audio(audio_bytes)
                if transcription:
                    user_text = f"[NOTA DE VOZ DEL CLIENTE] Transcripción: {transcription}"
                else:
                    user_text = "El cliente envió una nota de voz pero no se pudo transcribir."
            else:
                user_text = "El cliente envió una nota de voz pero no se pudo descargar."

        else:
            print(f"❓ Tipo no soportado: {msg_type}")
            return

        if not user_text:
            return

        print(f"🧠 Generando respuesta para {phone_number}...", flush=True)
        answer = await get_sales_response(phone_number, user_text)
        print(f"🗣️ Sofía: {answer}", flush=True)
        await send_whatsapp_message(phone_number, answer)

    except Exception as e:
        import traceback
        print(f"🚨 Error procesando evento: {e}", flush=True)
        traceback.print_exc()
