import os
import hmac
import hashlib
import json
import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Cargamos las variables de entorno
load_dotenv()

app = FastAPI(title="OMNI Bot - Cursos de Peluquería")

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

# Almacenamiento simple en memoria para el estado de conversación por usuario
user_states = {}

# --- RESPUESTAS PREDETERMINADAS ---
WELCOME_MESSAGE = """👋 ¡Hola! Bienvenido a nuestra academia de peluquería ✂️

Por favor, elige un curso para ver más información:

1️⃣ Curso 1: Corte de cabello para Dama
2️⃣ Curso 2: Barbería y Corte de caballero
3️⃣ Curso 3: Cortes infantiles / Peinados

Responde con el número del curso que te interesa 👇"""

COURSE_1 = """✂️ Curso 1: Corte de cabello para Dama

⏱️ Duración: 4 semanas
💰 Precio: $150.000 COP

💬 Escribe "menu" para ver otras opciones"""

COURSE_2 = """💈 Curso 2: Barbería y Corte de caballero

⏱️ Duración: 6 semanas
💰 Precio: $200.000 COP

💬 Escribe "menu" para ver otras opciones"""

COURSE_3 = """👧 Curso 3: Cortes infantiles / Peinados

⏱️ Duración: 3 semanas
💰 Precio: $120.000 COP

💬 Escribe "menu" para ver otras opciones"""

INVALID_OPTION = """❌ Opción no válida. Por favor, elige una opción del 1 al 3:

1️⃣ Curso 1: Corte de cabello para Dama
2️⃣ Curso 2: Barbería y Corte de caballero
3️⃣ Curso 3: Cortes infantiles / Peinados"""

# --- FUNCIONES LÓGICAS ---

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
        print(f"[MSG] Respuesta de Meta al enviar: {response.status_code}")
        if response.status_code != 200:
            print(f"[WARN] Detalle error Meta: {response.text}")

async def process_bot_message(phone_number: str, user_text: str):
    try:
        print(f"[BOT] Procesando mensaje de {phone_number}: {user_text}")
        
        # Normalizar el texto
        text = user_text.strip().lower()
        
        # Verificar si es un saludo inicial
        greetings = ["hola", "buenos", "buenas", "hi", "hello", "inicio", "empezar", "menu", "menú"]
        is_greeting = any(greeting in text for greeting in greetings)
        
        # Obtener estado actual del usuario
        current_state = user_states.get(phone_number, "welcome")
        
        # Función helper para procesar selección de curso
        async def handle_course_selection(text: str):
            if text in ["1", "curso 1", "curso1", "dama", "corte dama"]:
                await send_whatsapp_message(phone_number, COURSE_1)
                user_states[phone_number] = "course_selected"
                return True
            elif text in ["2", "curso 2", "curso2", "barberia", "barbería", "caballero", "corte caballero"]:
                await send_whatsapp_message(phone_number, COURSE_2)
                user_states[phone_number] = "course_selected"
                return True
            elif text in ["3", "curso 3", "curso3", "infantil", "infantiles", "peinados", "corte infantil"]:
                await send_whatsapp_message(phone_number, COURSE_3)
                user_states[phone_number] = "course_selected"
                return True
            return False
        
        if current_state == "welcome" or is_greeting:
            # Enviar mensaje de bienvenida con opciones
            user_states[phone_number] = "menu"
            await send_whatsapp_message(phone_number, WELCOME_MESSAGE)
            
        elif current_state == "menu":
            # Procesar selección de curso
            handled = await handle_course_selection(text)
            if not handled:
                await send_whatsapp_message(phone_number, INVALID_OPTION)
                
        elif current_state == "course_selected":
            # Permitir seleccionar otro curso directamente O volver al menú
            handled = await handle_course_selection(text)
            if not handled:
                if is_greeting or text in ["menu", "menú", "volver", "opciones", "otro"]:
                    user_states[phone_number] = "menu"
                    await send_whatsapp_message(phone_number, WELCOME_MESSAGE)
                else:
                    await send_whatsapp_message(phone_number, INVALID_OPTION)
                
    except Exception as e:
        print(f"[ERROR] ERROR CRITICO EN PROCESAMIENTO: {e}")

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"status": "OMNI Core Online"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print("[OK] WEBHOOK_VERIFIED")
        return Response(content=challenge, media_type="text/plain")
    
    return Response(content="Token invalido", status_code=403)

@app.post("/webhook")
async def receive_whatsapp(request: Request, x_hub_signature_256: str = Header(None)):
    body_bytes = await request.body()
    
    data = json.loads(body_bytes.decode('utf-8'))
    print(f"[JSON] JSON RECIBIDO: {json.dumps(data, indent=2)}")

    # Seguridad HMAC SHA-256
    if META_APP_SECRET and x_hub_signature_256:
        signature = hmac.new(META_APP_SECRET.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()
        if f"sha256={signature}" != x_hub_signature_256:
            print("[ERROR] Firma inválida")
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
                print(f"[MSG] Nuevo mensaje de {phone_number}: {user_text}")
                await process_bot_message(phone_number, user_text)
        else:
            print("[INFO] Webhook recibido pero no contiene mensajes.")
            
    except Exception as e:
        print(f"[ERROR] Error procesando JSON: {e}")

    return {"status": "received"}