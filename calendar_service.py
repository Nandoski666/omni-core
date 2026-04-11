import os.path
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# Alcance para gestionar el calendario
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    creds = None
    # Prioridad 1: Variable de entorno (Para Render.com)
    env_token = os.getenv("GOOGLE_TOKEN_JSON")
    if env_token:
        print("Usando token desde variable de entorno.")
        creds = Credentials.from_authorized_user_info(json.loads(env_token), SCOPES)
    
    # Prioridad 2: Archivo local (Para desarrollo local)
    elif os.path.exists('token.json'):
        print("Usando token desde archivo local.")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
            
    return build('calendar', 'v3', credentials=creds)

def create_event(summary, start_time_str, duration_minutes=30):
    """
    Crea un evento en Google Calendar.
    start_time_str debe estar en formato ISO (ej: 2026-04-10T15:00:00)
    """
    service = get_calendar_service()
    if not service:
        return "Error: No se encontró token de acceso. Por favor ejecuta 'python calendar_auth.py'."

    try:
        start_time = datetime.fromisoformat(start_time_str)
        end_time = start_time + timedelta(minutes=duration_minutes)

        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'America/Bogota', # Ajusta según tu zona horaria
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/Bogota',
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"✅ Evento creado: {event.get('htmlLink')}"
    except Exception as e:
        return f"❌ Error al crear evento: {str(e)}"
