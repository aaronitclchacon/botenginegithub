# telegram.py
import os
from telethon import TelegramClient, events
import logging
import sys
import asyncio
import nest_asyncio
from datetime import datetime, timezone
import requests
import json
from telethon.tl.types import (
    MessageEntityMention, MessageEntityMentionName, User, Chat, Channel,
    MessageMediaPhoto, MessageMediaDocument, MessageEntityUrl,
    MessageEntityTextUrl, MessageEntityEmail, MessageEntityBotCommand
)

nest_asyncio.apply()

# Directorio padre
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
from langgraph.agente_impersonador import create_langgraph_agent

# --- ID de Sesión y Rutas de Datos ---
SESSION_ID = os.getenv("SESSION_ID", "default_telegram")
# Si DATA_PATH no está definida, usar la raíz del proyecto como fallback.
DATA_PATH = os.getenv("DATA_PATH", project_root)
logging.info(f"Iniciando sesión de Telegram con ID: {SESSION_ID}")
logging.info(f"Usando DATA_PATH: {DATA_PATH}")

# Usar rutas absolutas basadas en DATA_PATH para evitar problemas de CWD
NEED_TELEGRAM_CODE_FILE = os.path.join(DATA_PATH, f"telegram_needs_code_{SESSION_ID}.txt")
TELEGRAM_CODE_FILE = os.path.join(DATA_PATH, f"telegram_code_{SESSION_ID}.txt")
TELEGRAM_AUTH_STATUS_FILE = os.path.join(DATA_PATH, f"telegram_auth_status_{SESSION_ID}.txt")
TELEGRAM_ERROR_FILE = os.path.join(DATA_PATH, f"telegram_error_{SESSION_ID}.txt")
SESSION_FILE = os.path.join(DATA_PATH, f"chatbot_session_{SESSION_ID}.session")
AUTH_CONNECTED = "connected"
AUTH_AUTHENTICATED = "authenticated"

# --- Obtener credenciales de variables de entorno ---
api_id_str = os.getenv("API_ID")
api_hash = os.getenv("API_HASH") 
phone_number = os.getenv("PHONE_NUMBER")
PHISHING_API_USER = os.getenv("PHISHING_API_USER")
PHISHING_API_PASSWORD = os.getenv("PHISHING_API_PASSWORD")
TOKEN_URL = os.getenv("TOKEN_URL")
PHISHING_API_URL = os.getenv("PHISHING_API_URL")

phishing_jwt_token = None # Variable global para el token

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Verificar credenciales ---
if not all([api_id_str, api_hash, phone_number, PHISHING_API_USER, PHISHING_API_PASSWORD, TOKEN_URL, PHISHING_API_URL]):
    error_msg = "Error: Faltan variables de entorno críticas para Telegram o la API de Phishing."
    logging.error(error_msg)
    with open(TELEGRAM_ERROR_FILE, "w") as f:
        f.write(error_msg)
    sys.exit(1)

try:
    api_id = int(api_id_str)
except ValueError:
    error_msg = "Error: API_ID debe ser un número entero."
    logging.error(error_msg)
    with open(TELEGRAM_ERROR_FILE, "w") as f:
        f.write(error_msg)
    sys.exit(1)

# --- Funciones para la API de Phishing ---
def generate_jwt_token():
    global phishing_jwt_token
    logging.info(f"Generando token JWT desde: {TOKEN_URL}")
    payload = {"username": PHISHING_API_USER, "password": PHISHING_API_PASSWORD}
    try:
        response = requests.post(TOKEN_URL, json=payload)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access")
        if access_token:
            logging.info("Token de ACCESO JWT generado exitosamente.")
            phishing_jwt_token = access_token
        else:
            logging.error("Error: El campo 'access' no se encontró en la respuesta del token.")
            phishing_jwt_token = None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de conexión al generar token: {e}")
        phishing_jwt_token = None

def send_to_phishing_api(sample_data):
    global phishing_jwt_token
    if not phishing_jwt_token:
        logging.warning("Token JWT no disponible. Intentando generar uno nuevo.")
        generate_jwt_token()
        if not phishing_jwt_token:
            logging.error("Fallo al generar nuevo token. No se enviará la muestra.")
            return None

    try:
        # Preparar los archivos adjuntos si existen
        files = {}
        file_handles = []  # Lista para mantener los archivos abiertos
        
        if 'message_content' in sample_data['sample'] and 'attachments' in sample_data['sample']['message_content']:
            attachments = sample_data['sample']['message_content']['attachments']
            for idx, attachment in enumerate(attachments):
                if 'file_path' in attachment:
                    file_path = attachment['file_path']
                    if os.path.exists(file_path):
                        # Abrir el archivo en modo binario y mantenerlo abierto
                        f = open(file_path, 'rb')
                        file_handles.append(f)  # Guardar referencia para cerrar después
                        files[f'file_{idx}'] = (
                            attachment['filename'],
                            f,
                            'application/octet-stream'
                        )
                        # Eliminar la ruta del archivo del payload JSON
                        attachment_copy = attachment.copy()
                        del attachment_copy['file_path']
                        sample_data['sample']['message_content']['attachments'][idx] = attachment_copy

        # Preparar headers y datos
        headers = {"Authorization": f"Bearer {phishing_jwt_token}"}
        
        # Si hay archivos, usar multipart/form-data
        if files:
            logging.info("Detectados adjuntos. Preparando envío multipart/form-data.")
            # Eliminar la ruta del archivo del payload JSON antes de enviarlo
            sanitized_sample_data = json.loads(json.dumps(sample_data)) # Copia profunda
            if 'attachments' in sanitized_sample_data.get('sample', {}).get('message_content', {}):
                for att in sanitized_sample_data['sample']['message_content']['attachments']:
                    att.pop('file_path', None)
            
            response = requests.post(
                PHISHING_API_URL,
                headers=headers,
                data={'sample': json.dumps(sanitized_sample_data)},
                files=files
            )
        else:
            # Si no hay archivos, usar JSON directo
            headers["Content-Type"] = "application/json"
            response = requests.post(PHISHING_API_URL, json=sample_data, headers=headers)

        response.raise_for_status()
        logging.info("Muestra enviada exitosamente a la API de Phishing.")

        # Cerrar todos los archivos abiertos
        for f in file_handles:
            try:
                f.close()
            except Exception as e:
                logging.error(f"Error al cerrar archivo: {e}")

        # Limpiar archivos temporales después del envío exitoso
        if file_handles:
            if 'message_content' in sample_data['sample'] and 'attachments' in sample_data['sample']['message_content']:
                attachments = sample_data['sample']['message_content']['attachments']
                for attachment in attachments:
                    if 'file_path' in attachment:
                        try:
                            os.remove(attachment['file_path'])
                            logging.info(f"Archivo temporal eliminado: {attachment['file_path']}")
                        except Exception as e:
                            logging.error(f"Error al eliminar archivo temporal: {e}")

        return response.json()

    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 401:
            logging.info("Token posiblemente expirado. Regenerando y reenviando.")
            generate_jwt_token()
            if phishing_jwt_token:
                return send_to_phishing_api(sample_data)  # Reintentar con nuevo token
        logging.error(f"Error HTTP: {http_err}")
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Error de conexión al enviar la muestra: {req_err}")
    except Exception as e:
        logging.error(f"Error inesperado al enviar la muestra: {e}")
    
    # Asegurarse de cerrar y limpiar archivos en caso de cualquier error
    for f in file_handles:
        try:
            f.close()
        except Exception as e:
            logging.error(f"Error al cerrar archivo en bloque de error: {e}")

    if 'message_content' in sample_data['sample'] and 'attachments' in sample_data['sample']['message_content']:
        for attachment in sample_data['sample']['message_content']['attachments']:
            if 'file_path' in attachment and os.path.exists(attachment['file_path']):
                try:
                    os.remove(attachment['file_path'])
                    logging.info(f"Archivo temporal eliminado después de error: {attachment['file_path']}")
                except Exception as e:
                    logging.error(f"Error al limpiar archivos temporales en bloque de error: {e}")
    
    return None


client = TelegramClient(SESSION_FILE, api_id, api_hash)
compiled_graph, _ = create_langgraph_agent()

async def main():
    try:
        logging.info("Iniciando cliente de Telegram...")
        await client.connect()
        logging.info("Cliente de Telegram conectado.")

        is_authorized = await client.is_user_authorized()
        if is_authorized:
            with open(TELEGRAM_AUTH_STATUS_FILE, "w") as f: f.write(AUTH_CONNECTED)
        else:
            if os.path.exists(TELEGRAM_AUTH_STATUS_FILE): os.remove(TELEGRAM_AUTH_STATUS_FILE)

        if not is_authorized:
            try:
                await client.send_code_request(phone_number)
                with open(NEED_TELEGRAM_CODE_FILE, "w") as f: f.write("waiting")
                logging.info("Código enviado. Esperando entrada del usuario desde la interfaz.")
                
                code_verified = False
                for _ in range(60):
                    if os.path.exists(TELEGRAM_CODE_FILE):
                        with open(TELEGRAM_CODE_FILE, "r") as f: code = f.read().strip()
                        os.remove(TELEGRAM_CODE_FILE)
                        try:
                            await client.sign_in(phone_number, code)
                            if os.path.exists(NEED_TELEGRAM_CODE_FILE): os.remove(NEED_TELEGRAM_CODE_FILE)
                            with open(TELEGRAM_AUTH_STATUS_FILE, "w") as f: f.write(AUTH_CONNECTED)
                            code_verified = True
                            break
                        except Exception as e:
                            logging.error(f"Error al iniciar sesión con el código: {e}")
                            with open(TELEGRAM_ERROR_FILE, "w") as f: f.write(str(e))
                    await asyncio.sleep(5)
                
                if not code_verified: raise Exception("Timeout: No se recibió código válido.")
            except Exception as e:
                logging.error(f"Error durante la autenticación: {e}")
                with open(TELEGRAM_ERROR_FILE, "w") as f: f.write(str(e))
                await client.disconnect()
                return

        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            if await event.get_sender() and (await event.get_sender()).bot:
                return # Ignorar mensajes de otros bots

            me = await client.get_me()
            if event.sender_id == me.id:
                return # Ignorar mensajes propios

            logging.info("---- Nuevo Mensaje de Telegram Recibido ----")
            message_data = {}

            # 1. Remitente (ID y Nombre)
            sender = await event.get_sender()
            message_data['remitenteID'] = sender.id
            sender_name = sender.first_name or "Desconocido"
            if sender.last_name:
                sender_name += f" {sender.last_name}"
            message_data['nombreRemitente'] = sender_name
            message_data['usernameRemitente'] = sender.username or "N/A"

            # 2. Chat ID y Título del Chat / Es un Grupo
            chat = await event.get_chat()
            is_group = isinstance(chat, (Chat, Channel))
            message_data['esUnGrupo'] = is_group
            message_data['tituloChat'] = chat.title if is_group else "Chat Privado"

            # 3. Contenido del Mensaje
            message_text = event.raw_text
            message_data['contenidoMensaje'] = message_text

            # 5. Hora y 6. ID
            message_data['timestampUnix'] = event.date.timestamp()
            message_data['idMensaje'] = event.id
            
            # 7. Mensaje reenviado
            message_data['esReenviado'] = bool(event.forward)

            # 8. Mensaje citado
            message_data['esRespuesta'] = event.is_reply

            # 9. Tipo de Mensaje y MIME Type
            if event.media:
                if isinstance(event.media, MessageMediaPhoto):
                    message_data['tipoMensaje'] = "image"
                    message_data['mimeType'] = "image/jpeg"
                elif isinstance(event.media, MessageMediaDocument):
                    mime_type = event.media.document.mime_type
                    message_data['mimeType'] = mime_type
                    
                    # Determinar tipo de mensaje basado en MIME type
                    if mime_type:
                        if mime_type.startswith('audio/') or mime_type == 'application/ogg':
                            message_data['tipoMensaje'] = "audio"
                        elif mime_type.startswith('image/'):
                            message_data['tipoMensaje'] = "image"
                        elif mime_type.startswith('video/'):
                            message_data['tipoMensaje'] = "video"
                        else:
                            message_data['tipoMensaje'] = "document"
                    else:
                        message_data['tipoMensaje'] = "document"
                else:
                    message_data['tipoMensaje'] = "media"
                    message_data['mimeType'] = "unknown"
            else:
                message_data['tipoMensaje'] = "text"
                message_data['mimeType'] = None

            # 10. Menciones
            bot_was_mentioned = False
            if event.mentioned:
                if me.id in [user.id for user in await event.get_mentioned_users()]:
                    bot_was_mentioned = True
            message_data['botFueMencionado'] = bot_was_mentioned

            # --- Procesar archivos adjuntos ---
            attachments = []
            if event.media:
                try:
                    # Crear directorio temporal dentro de DATA_PATH si no existe
                    temp_dir = os.path.join(DATA_PATH, "temp_media")
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    # Generar nombre único para el archivo
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_path = os.path.join(temp_dir, f"telegram_{event.id}_{timestamp}")
                    
                    # Descargar el archivo
                    downloaded_file = await event.download_media(file=file_path)
                    
                    if downloaded_file:
                        # Obtener información del archivo
                        file_size = os.path.getsize(downloaded_file)
                        file_type = "unknown"
                        if isinstance(event.media, MessageMediaPhoto):
                            file_type = "image"
                        elif isinstance(event.media, MessageMediaDocument):
                            if event.media.document.mime_type:
                                file_type = event.media.document.mime_type
                                if file_type.startswith("audio/"):
                                    file_type = "audio"
                                elif file_type.startswith("image/"):
                                    file_type = "image"
                        
                        # Crear datos del adjunto
                        attachment_data = {
                            "type": file_type,
                            "filename": os.path.basename(downloaded_file),
                            "size": file_size,
                            "file_path": downloaded_file
                        }
                        attachments.append(attachment_data)
                        logging.info(f"Archivo adjunto procesado: {attachment_data}")
                except Exception as e:
                    logging.error(f"Error al procesar archivo adjunto: {e}")

            # --- Lógica de la API de Phishing ---
            try:
                phishing_payload = {
                    "sample": {
                        "message_id": str(event.id),
                        "platform": "telegram",
                        "chat_type": "group" if is_group else "private",
                        "from": sender_name,
                        "to": me.first_name or "BotEngine",
                        "sender_info": {"user_id": str(sender.id), "username": sender.username or "N/A", "is_bot": 1 if sender.bot else 0},
                        "message_content": {
                            "text": message_text,
                            "attachments": attachments
                        },
                        "timestamp": event.date.isoformat(),
                    }
                }
                api_response = send_to_phishing_api(phishing_payload)
                message_data['phishingApiResponse'] = api_response or "No se obtuvo respuesta"
                if api_response and api_response.get("bot_responses", {}).get("technical_response", {}).get("text"):
                    await event.reply(f"Alerta de Seguridad: {api_response['bot_responses']['technical_response']['text']}")
            except Exception as e:
                logging.error(f"Error al procesar con la API de Phishing: {e}")

            # --- Lógica del Agente Conversacional ---
            if (is_group and bot_was_mentioned) or (not is_group):
                try:
                    # Preparar el mensaje para el agente
                    input_message = message_text
                    if not input_message:
                        # Construir mensaje basado en el tipo de contenido y resultado del análisis
                        tipo_mensaje = message_data.get('tipoMensaje')
                        phishing_response = message_data.get('phishingApiResponse', {})
                        is_phishing = phishing_response.get('analysis_results', {}).get('is_phishing', False)
                        
                        if is_phishing:
                            # Si se detectó phishing, incluir esa información en el mensaje
                            input_message = f"[Se ha detectado contenido sospechoso en el {tipo_mensaje} enviado]"
                        else:
                            # Mensaje específico según el tipo de contenido
                            if tipo_mensaje == "image":
                                input_message = "[El usuario ha enviado una imagen]"
                            elif tipo_mensaje == "audio":
                                input_message = "[El usuario ha enviado un mensaje de voz o archivo de audio]"
                            elif tipo_mensaje == "video":
                                input_message = "[El usuario ha enviado un video]"
                            elif tipo_mensaje == "document":
                                mime_type = message_data.get('mimeType', '')
                                input_message = f"[El usuario ha enviado un archivo de tipo: {mime_type or 'desconocido'}]"
                            else:
                                input_message = "[El usuario ha enviado un archivo multimedia]"

                    result = await compiled_graph.ainvoke(
                        {"input": input_message},
                        config={"configurable": {"thread_id": str(sender.id)}}
                    )
                    reply = result["output"]
                    message_data['respuestaBot'] = reply
                    await event.reply(reply)
                except Exception as e:
                    logging.error(f"Error al generar respuesta para {sender_name}: {e}")
                    message_data['errorAgente'] = str(e)
            else:
                 message_data['respuestaBot'] = "No se respondió (mensaje en grupo sin mención)."

            # --- JSON Output Final ---
            logging.info(f"--- Datos del Mensaje en JSON ---\n{json.dumps(message_data, indent=2, ensure_ascii=False, default=str)}")
            logging.info("--- Fin del Procesamiento de Mensaje ---")

        # Indicar que el agente está listo
        logging.info("Creando agente LangGraph...")
        global compiled_graph
        compiled_graph, _ = create_langgraph_agent()
        logging.info("Agente LangGraph creado.")

        # Escribir el estado final "authenticated"
        with open(TELEGRAM_AUTH_STATUS_FILE, "w") as f:
            f.write(AUTH_AUTHENTICATED)
        logging.info("Estado AUTENTICADO para Streamlit guardado.")

        generate_jwt_token() # Generar token al inicio
        print("🤖 BotEngine activo en Telegram... esperando mensajes")
        await client.run_until_disconnected()

    except Exception as e:
        logging.error(f"Error general en Telegram: {e}")
        if client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())