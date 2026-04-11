import os
import hmac
import hashlib
import json
import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import AsyncGroq
from dotenv import load_dotenv
from datetime import datetime
import base64

# Cargamos las variables de entorno
load_dotenv()

app = FastAPI(title="OMNI Neural Core - B2B Agency Edition")

# --- CONFIGURACIÓN ---
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "omni_pro_2026")
META_APP_SECRET = os.getenv("META_APP_SECRET") 
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") 
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") 
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v18.0")

# --- MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializamos Groq en modo Asíncrono 🚀
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

class ChatRequest(BaseModel):
    prompt: str

# --- MEMORIA RAM TEMPORAL ---
# Aquí guardamos el contexto para que el bot no pierda el hilo de la charla
active_sessions = {}

# --- MODELO DE VISIÓN ---
# Nota: Si este modelo falla, intenta con 'llama-3.2-90b-vision-preview'
VISION_MODEL = "llama-3.2-11b-vision-preview"

# --- FUNCIONES LÓGICAS ---

from calendar_service import create_event

# --- FUNCIONES LÓGICAS ---

# Definición de herramientas para Groq
tools = [
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Crea un evento en el calendario de Google",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Título del evento o descripción breve",
                    },
                    "start_time_str": {
                        "type": "string",
                        "description": "Fecha y hora de inicio en formato ISO 8601 (ej: 2026-04-10T15:00:00)",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duración en minutos (por defecto 30)",
                    },
                },
                "required": ["summary", "start_time_str"],
            },
        },
    }
]

async def get_omni_response(phone_number: str, user_text: str):
    # 1. El Cerebro Dinámico: Asistente Personal Amigable
    business_context = os.getenv(
        "BUSINESS_PROMPT", 
        "Eres mi Asistente Personal y Gestor de Agenda (IA). Soy tu jefe y creador.\n"
        "Tu tono debe ser súper amigable, entusiasta y muy servicial.\n\n"
        "Tus objetivos y comportamiento:\n"
        "1. SALUDOS: Si solo te digo 'Hola' o algo casual, responde con entusiasmo recordando que puedes agendar citas.\n"
        "2. CAPTURA DE DATOS: Necesitas Nombre del Evento, Fecha y Hora para agendar.\n"
        "3. ACCIÓN: Cuando tengas los datos, utiliza la herramienta 'create_event' para agendarlo de verdad.\n"
        "4. IMÁGENES Y PAGOS: A veces recibirás descripciones de imágenes (como comprobantes de pago). En ese caso, confirma los datos (Banco, Monto, Referencia) y felicita al usuario por su pago o agenda la cita si la imagen era un flyer.\n"
        "HOY ES: " + datetime.now().strftime("%A, %d de %B de %Y, hora %I:%M %p")
    )
    
    strict_rules = """
    Reglas Estrictas:
    - NUNCA inventes datos si no los doy.
    - Responde siempre en un solo párrafo corto (máx 40 palabras).
    - Si usas la herramienta create_event, confirma al usuario que ya quedó agendado.
    """
    
    full_system_prompt = f"{business_context}\n\n{strict_rules}"

    if phone_number not in active_sessions:
        active_sessions[phone_number] = [{"role": "system", "content": full_system_prompt}]
    
    active_sessions[phone_number].append({"role": "user", "content": user_text})

    try:
        # 5. Generar respuesta con soporte para herramientas
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=active_sessions[phone_number],
            tools=tools,
            tool_choice="auto",
            max_tokens=150,
            temperature=0.2
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        # Si la IA quiere llamar a una herramienta (agendar cita)
        if tool_calls:
            active_sessions[phone_number].append(response_message)
            
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                if function_name == "create_event":
                    print(f"📅 Agendando: {function_args}")
                    result = create_event(
                        summary=function_args.get("summary"),
                        start_time_str=function_args.get("start_time_str"),
                        duration_minutes=function_args.get("duration_minutes", 30)
                    )
                    
                    active_sessions[phone_number].append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": result,
                    })
            
            # Segunda llamada para que la IA dé la respuesta final basada en el resultado del agendamiento
            final_response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=active_sessions[phone_number]
            )
            ai_answer = final_response.choices[0].message.content
        else:
            ai_answer = response_message.content

        active_sessions[phone_number].append({"role": "assistant", "content": ai_answer})
        
        if len(active_sessions[phone_number]) > 12:
            active_sessions[phone_number] = [active_sessions[phone_number][0]] + active_sessions[phone_number][-6:]

        return ai_answer

    except Exception as e:
        print(f"❌ Error: {e}")
        return "Lo siento jefe, tuve un problemita técnico. ¿Me repites?"


async def download_whatsapp_media(media_id: str):
    """Descarga un archivo de medios (imagen) de WhatsApp."""
    url = f"{WHATSAPP_API_URL}/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    async with httpx.AsyncClient() as http_client:
        # 1. Obtener la URL de descarga
        response = await http_client.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Error al obtener URL de medios: {response.text}")
            return None
        
        media_url = response.json().get("url")
        if not media_url:
            return None
            
        # 2. Descargar el archivo binario
        media_response = await http_client.get(media_url, headers=headers)
        if media_response.status_code != 200:
            print(f"❌ Error al descargar medios: {media_response.text}")
            return None
            
        return media_response.content

async def analyze_image_with_vision(image_bytes: bytes):
    """Usa el modelo de visión de Groq para extraer datos de la imagen."""
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        prompt = (
            "Eres un experto en extracción de datos. Analiza esta imagen enviada por un cliente.\n"
            "1. Si es un COMPROBANTE DE PAGO: Extrae Banco, Monto, Fecha y Referencia.\n"
            "2. Si es para una CITA/CALENDARIO: Extrae Título del evento, Fecha, Hora y descripción.\n"
            "Responde con un resumen claro de lo que encontraste para que yo pueda procesarlo."
        )
        
        response = await client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            max_tokens=300,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Error en Groq Vision: {e}")
        return "No pude leer la imagen correctamente."

async def send_whatsapp_message(to_phone: str, text: str):
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
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(url, json=payload, headers=headers)
        print(f"📩 Respuesta de Meta al enviar: {response.status_code}")
        if response.status_code != 200:
            print(f"⚠️ Detalle error Meta: {response.text}")

async def process_whatsapp_ai(phone_number: str, user_text: str):
    try:
        print(f"🧠 Pensando respuesta para {phone_number}...")
        # ⚠️ IMPORTANTE: Aquí ahora le pasamos el phone_number a Groq para la memoria
        ai_answer = await get_omni_response(phone_number, user_text)
        print(f"🗣️ OMNI dice: {ai_answer}")
        await send_whatsapp_message(phone_number, ai_answer)
    except Exception as e:
        print(f"🚨 ERROR CRÍTICO EN PROCESAMIENTO: {e}")

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"status": "OMNI Core Online 🚀"}

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
    
    data = json.loads(body_bytes.decode('utf-8'))
    print(f"🔍 JSON RECIBIDO: {json.dumps(data, indent=2)}")

    # Seguridad HMAC SHA-256
    if META_APP_SECRET and x_hub_signature_256:
        signature = hmac.new(META_APP_SECRET.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()
        if f"sha256={signature}" != x_hub_signature_256:
            print("❌ Firma inválida")
            raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "messages" in value:
            message = value["messages"][0]
            phone_number = message["from"]
            msg_type = message.get("type")
            
            user_text = ""
            
            if msg_type == "text":
                user_text = message.get("text", {}).get("body", "")
                print(f"🌊 Nuevo mensaje de {phone_number}: {user_text}")
                
            elif msg_type == "image":
                image_data = message.get("image", {})
                media_id = image_data.get("id")
                caption = image_data.get("caption", "")
                
                print(f"📸 Imagen recibida de {phone_number}. ID: {media_id}")
                
                # Enviar confirmación inmediata para que el usuario sepa que algo está pasando
                await send_whatsapp_message(phone_number, "📸 He recibido tu imagen, jefe. Dame un momento para analizarla...")
                
                image_bytes = await download_whatsapp_media(media_id)
                if image_bytes:
                    print(f"✅ Imagen descargada ({len(image_bytes)} bytes). Analizando con {VISION_MODEL}...")
                    analysis = await analyze_image_with_vision(image_bytes)
                    print(f"📝 Análisis completado: {analysis[:50]}...")
                    user_text = f"[IMAGEN ENVIADA POR USUARIO] - Descripción de la IA: {analysis}"
                    if caption:
                        user_text += f"\nComentario del usuario: {caption}"
                else:
                    print("❌ Falló la descarga de la imagen.")
                    user_text = "El usuario envió una imagen pero no pude descargarla. Por favor verifica los permisos del token de WhatsApp para leer media."
            
            else:
                print(f"❓ Tipo de mensaje no soportado: {msg_type}")
            
            if user_text:
                # 🔥 EJECUCIÓN DIRECTA
                await process_whatsapp_ai(phone_number, user_text)
        else:
            print("ℹ️ Webhook recibido pero no contiene mensajes.")
            
    except Exception as e:
        print(f"❌ Error procesando JSON: {e}")

    return {"status": "received"}