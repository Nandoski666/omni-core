import os
import hmac
import hashlib
import json
import time
import asyncio
import base64
import io

import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq
from dotenv import load_dotenv

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

LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
VISION_MODEL = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
FALLBACK_VISION_MODEL = os.getenv("FALLBACK_VISION_MODEL", "llama-3.2-11b-vision-preview")
AUDIO_MODEL = os.getenv("AUDIO_MODEL", "whisper-large-v3")

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_HOURS", "24")) * 3600
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

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
SYSTEM_PROMPT_TEMPLATE = """Eres "Sofía", asesora de ventas senior de {BRAND_NAME} ({SALES_URL}). Escribes por WhatsApp a clientes que llegaron desde un anuncio de Facebook/Instagram promocionando:
"{CURRENT_PRODUCT}" — {CURRENT_PRODUCT_ANGLE}

MISIÓN: hacer sentir escuchado al cliente, resolver dudas y guiarlo a comprar en {SALES_URL}.

TONO Y ESTILO:
- Humana, cálida, cercana. 1-2 emojis por mensaje MÁXIMO.
- Mensajes CORTOS estilo WhatsApp: 2-4 líneas, máximo 50 palabras.
- Español neutro LATAM, tuteo.
- Nunca digas que eres IA, bot ni asistente virtual. Si preguntan directamente: "soy parte del equipo de {BRAND_NAME}".

MÉTODO DE VENTA (SPIN adaptado):
1. SALUDO Y CONEXIÓN: si es el primer mensaje, saluda con calidez, agradece que escribió y pregunta ABIERTA qué le llamó la atención del anuncio o qué necesita.
2. DESCUBRIMIENTO: haz 1-2 preguntas cortas para entender uso, urgencia y para quién. UNA pregunta por mensaje, nunca interrogatorio.
3. VALIDACIÓN: refleja lo que entendiste con empatía ("Entiendo, buscas X porque Y...").
4. PROPUESTA: explica cómo {CURRENT_PRODUCT} resuelve su necesidad SIN inventar precios, stock, tallas, colores, plazos ni promociones. Habla de beneficios y experiencia.
5. MANEJO DE OBJECIONES: Precio → valor y facilidad de compra. Duda → seguridad y soporte. Tiempo → invita a ver detalles sin presión.
6. CIERRE Y REDIRECCIÓN: cuando muestre interés real (pregunta precio, disponibilidad, "cómo compro", "quiero uno"), envía:
   "Aquí ves todos los detalles, precios actualizados y compras en 2 minutos: {SALES_URL} — cuando lo abras me avisas si te ayudo con algo 💜"
   NO mandes el link en el primer mensaje. Solo tras generar interés.

REGLAS ESTRICTAS (NO NEGOCIABLES):
- JAMÁS inventes precios, descuentos, stock, tiempos de envío, garantías específicas, métodos de pago ni políticas. Si preguntan, responde: "Los precios y detalles siempre actualizados están aquí: {SALES_URL}".
- Si el cliente se enoja, insulta, pide reembolso, reporta un pedido con problema, o pide hablar con un humano: responde "Entiendo, voy a pasar tu caso a un asesor humano ahora mismo para que te atienda personalmente 🙏" y NO intentes resolverlo tú.
- Si envían foto de un producto ("quiero algo así"), confirma qué viste y redirige a {SALES_URL} sugiriendo buscar por categoría.
- Nunca hables de temas ajenos a {BRAND_NAME}.
- Un mensaje = una idea. No listes 5 preguntas juntas.
"""


def build_system_prompt() -> str:
    product = CURRENT_PRODUCT or "nuestros productos destacados"
    angle = CURRENT_PRODUCT_ANGLE or "productos seleccionados con mucho cuidado para nuestros clientes"
    return SYSTEM_PROMPT_TEMPLATE.format(
        BRAND_NAME=BRAND_NAME,
        SALES_URL=SALES_URL,
        CURRENT_PRODUCT=product,
        CURRENT_PRODUCT_ANGLE=angle,
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

async def get_sales_response(phone: str, user_text: str) -> str:
    messages = append_to_session(phone, {"role": "user", "content": user_text})
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=180,
            temperature=0.6,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Groq error: {e}")
        answer = "Perdona, tuve un problemita técnico 🙏 ¿Me repites en un momento?"
    append_to_session(phone, {"role": "assistant", "content": answer})
    return answer


# --- ENDPOINTS ---

@app.get("/")
def home():
    return {
        "status": "online",
        "brand": BRAND_NAME,
        "sales_url": SALES_URL,
        "current_product": CURRENT_PRODUCT or "(genérico)",
    }


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
        print(f"❌ JSON inválido: {e}")
        return {"status": "invalid_json"}

    # Responder rápido a Meta y procesar en background
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
            print(f"🌊 {phone_number}: {user_text}")

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

        print(f"🧠 Generando respuesta para {phone_number}...")
        answer = await get_sales_response(phone_number, user_text)
        print(f"🗣️ Sofía: {answer}")
        await send_whatsapp_message(phone_number, answer)

    except Exception as e:
        print(f"🚨 Error procesando evento: {e}")
