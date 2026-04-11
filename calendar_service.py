import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# Alcance para gestionar el calendario
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Si llegamos aquí sin token, hay que correr calendar_auth.py primero
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
