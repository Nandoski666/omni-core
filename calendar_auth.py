import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Solo alcance para gestionar el calendario completo (lectura y escritura)
SCOPES = ['https://www.googleapis.com/auth/calendar']

def main():
    creds = None
    # El archivo token.json almacena el token de acceso y actualización de tu cuenta
    # Se crea automáticamente cuando la autorización inicial finaliza.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    # Si no hay credenciales válidas disponibles, haz que el usuario inicie sesión.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refrescando token caducado...")
            creds.refresh(Request())
        else:
            print("Iniciando flujo de validación. Revisa tu navegador web...")
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            # Levantar servidor local en un puerto disponible, se cerrará solo. 
            creds = flow.run_local_server(port=0)
            
        # Guardar las credenciales para la próxima vez
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    print("\n✅ ¡Autenticación de Google exitosa! El archivo 'token.json' está listo.")

if __name__ == '__main__':
    main()
