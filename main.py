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

# --- FUNCIONES LÓGICAS ---

async def get_omni_response(phone_number: str, user_text: str):
    # 1. El Cerebro Dinámico: Asistente Personal Amigable
    business_context = os.getenv(
        "BUSINESS_PROMPT", 
        "Eres mi Asistente Personal y Gestor de Agenda (IA). Soy tu jefe y creador.\n"
        "Tu tono debe ser súper amigable, entusiasta y muy servicial.\n\n"
        "Tus objetivos y comportamiento:\n"
        "1. SALUDOS: Si solo te digo 'Hola', 'Buenos días' o te saludo, JAMÁS respondas algo genérico como '¿En qué puedo ayudarte?'. Siempre responde con entusiasmo recordando tu función, por ejemplo: '¡Hola! Estoy aquí listo para ayudarte a agendar todas tus citas, recordatorios y eventos. ¿Qué planes tienes hoy?'\n"
        "2. CAPTURA DE DATOS: Cuando te cuente un plan, evento o tarea, tu misión es capturar el Nombre del Evento, la Fecha y la Hora para poder agendarlo.\n"
        "3. PREGUNTAS AMIGABLES: Si me falta decirte la hora o el día, pregúntamelo de forma cercana (ej. '¡Súper! ¿A qué hora lo programamos?').\n"
        "4. CONFIRMACIÓN: Cuando ya tengas los datos, confirmo con buena energía (ej. '¡Anotado! He agendado la salida de mañana a las 8:00 PM.')."
    )
    
    # 2. Las Reglas de Hierro y Protocolo
    strict_rules = """
    Reglas Estrictas de Comportamiento:
    - NUNCA des explicaciones largas ni actúes como robot frío. Eres alguien con buena vibra.
    - NO eres servicio al cliente ni vendedor; eres mi secretario personal.
    - Haz MÁXIMO UNA pregunta por mensaje.
    - Resuelve la interacción en un solo párrafo corto (máximo 40 palabras).
    """
    
    full_system_prompt = f"{business_context}\n\n{strict_rules}"

    # 3. Inicializar memoria si el cliente es nuevo
    if phone_number not in active_sessions:
        active_sessions[phone_number] = [
            {"role": "system", "content": full_system_prompt}
        ]
    
    # 4. Guardar mensaje del usuario
    active_sessions[phone_number].append({"role": "user", "content": user_text})

    try:
        # 5. Generar respuesta blindada
        chat_completion = await client.chat.completions.create(
            messages=active_sessions[phone_number],
            model="llama-3.3-70b-versatile",
            max_tokens=120, # Corta la labia
            temperature=0.2 # Más calculador, menos creativo
        )
        
        ai_answer = chat_completion.choices[0].message.content
        
        # 6. Guardar respuesta del bot en la memoria
        active_sessions[phone_number].append({"role": "assistant", "content": ai_answer})
        
        # 7. Limpiador de RAM (Mantiene el system prompt y los últimos 6 mensajes)
        if len(active_sessions[phone_number]) > 11:
            active_sessions[phone_number] = [active_sessions[phone_number][0]] + active_sessions[phone_number][-6:]

        return ai_answer

    except Exception as e:
        print(f"❌ Error en Groq: {e}")
        return "Eche, el sistema está saturado. ¿Me repites eso?"


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
            user_text = message.get("text", {}).get("body", "")
            
            if user_text:
                print(f"🌊 Nuevo mensaje de {phone_number}: {user_text}")
                # 🔥 EJECUCIÓN DIRECTA
                await process_whatsapp_ai(phone_number, user_text)
        else:
            print("ℹ️ Webhook recibido pero no contiene mensajes.")
            
    except Exception as e:
        print(f"❌ Error procesando JSON: {e}")

    return {"status": "received"}