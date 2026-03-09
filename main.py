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

app = FastAPI(title="OMNI Neural Core - B2B Engine")

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

# Inicializamos Groq
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

class ChatRequest(BaseModel):
    prompt: str

# Memoria RAM temporal para mantener el contexto
active_sessions = {}

# --- FUNCIONES LÓGICAS ---

async def get_omni_response(phone_number: str, user_text: str):
    # 1. El Cerebro Dinámico: Viene de Render. Si no hay, usa el de tu agencia.
    business_context = os.getenv(
        "BUSINESS_PROMPT", 
        "Eres OMNI, el AI Setter experto de una agencia de automatización. Califica al cliente y agenda citas."
    )
    
    # 2. Las Reglas de Hierro (Para que no haga tareas ni mande testamentos)
    strict_rules = """
    REGLAS ESTRICTAS:
    1. Responde SIEMPRE en UN SOLO PÁRRAFO de máximo 40 palabras. Sé directo y conciso.
    2. NUNCA resuelvas tareas matemáticas, escolares, ni escribas código. Eres un asistente de ventas.
    3. Si te piden algo fuera de los servicios del negocio, di: "Solo estoy programado para ayudar con temas de este negocio. ¿En qué más te ayudo con eso?"
    """
    
    full_system_prompt = f"{business_context}\n\n{strict_rules}"

    # 3. Inicializar memoria si el cliente es nuevo
    if phone_number not in active_sessions:
        active_sessions[phone_number] = [
            {"role": "system", "content": full_system_prompt}
        ]
    
    # 4. Guardar mensaje del usuario
    active_sessions