import discord
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from discord.ext import commands
import sys 

# Añadir el directorio padre al sys.path para encontrar el módulo langgraph
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
sys.path.append(project_root)

dotenv_path = os.path.join(project_root, '.env') # Ruta explícita al .env en la raíz
load_dotenv(dotenv_path) # Cargar el .env desde la ruta especificada

from langgraph.agente_impersonador import create_langgraph_agent # <--- Nueva importación

# Credenciales del Bot de Discord (debe estar en .env)
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Credenciales API Phishing (deben estar en .env)
PHISHING_API_USER = os.getenv("PHISHING_API_USER")
PHISHING_API_PASSWORD = os.getenv("PHISHING_API_PASSWORD")
TOKEN_URL = os.getenv("TOKEN_URL")
PHISHING_API_URL = os.getenv("PHISHING_API_URL")

# Verificar que todas las variables de entorno críticas estén definidas
if not DISCORD_TOKEN:
    print("Error: Falta la variable de entorno DISCORD_TOKEN.")
    print("Asegúrate de definirla en tu archivo .env")
    sys.exit(1)

if not (PHISHING_API_USER and PHISHING_API_PASSWORD and TOKEN_URL and PHISHING_API_URL):
    print("Error: Faltan variables de entorno críticas para la API de Phishing.")
    print("Asegúrate de definir PHISHING_API_USER, PHISHING_API_PASSWORD, TOKEN_URL, y PHISHING_API_URL en tu archivo .env")
    sys.exit(1)

# Variable global para el token
phishing_jwt_token = None

# Instancia del agente impersonador
impersonator_agent = None # Se inicializará en on_ready

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True # Necesario para message.guild
intents.members = True # Podría ser útil para obtener más info del autor

bot = commands.Bot(command_prefix='!', intents=intents)

# --- Funciones para la API de Phishing (adaptadas de telegram.py) ---
def generate_jwt_token():
    global phishing_jwt_token
    print(f"Generando token JWT desde: {TOKEN_URL}")
    payload = {
        "username": PHISHING_API_USER,
        "password": PHISHING_API_PASSWORD
    }
    try:
        response = requests.post(TOKEN_URL, json=payload)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access")
        if access_token:
            print("Token de ACCESO JWT generado exitosamente.")
            phishing_jwt_token = access_token
            return access_token
        else:
            print("Error: El campo 'access' no se encontró en la respuesta del token.")
            phishing_jwt_token = None
            return None
    except requests.exceptions.HTTPError as http_err:
        print(f"Error HTTP al generar token: {http_err} - Respuesta: {response.text}")
    except requests.exceptions.RequestException as req_err:
        print(f"Error de conexión al generar token: {req_err}")
    except json.JSONDecodeError:
        print("Error al decodificar la respuesta JSON del token.")
    phishing_jwt_token = None
    return None

def send_to_phishing_api(sample_data):
    global phishing_jwt_token
    if not phishing_jwt_token:
        print("No se puede enviar la muestra: token JWT no disponible. Intentando generar uno nuevo.")
        generate_jwt_token()
        if not phishing_jwt_token:
            print("Fallo al generar nuevo token. No se enviará la muestra.")
            return None

    print(f"Enviando muestra a la API de Phishing: {PHISHING_API_URL}")
    headers = {
        "Authorization": f"Bearer {phishing_jwt_token}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(PHISHING_API_URL, json=sample_data, headers=headers)
        response.raise_for_status()
        print("Muestra enviada exitosamente a la API de Phishing.")
        api_response = response.json()
        print(f"Respuesta de la API de Phishing: {json.dumps(api_response, indent=2, ensure_ascii=False)}")
        return api_response
    except requests.exceptions.HTTPError as http_err:
        print(f"Error HTTP al enviar la muestra a Phishing API: {http_err} - Respuesta: {response.text}")
        if response.status_code == 401: # Unauthorized
            print("Token posiblemente expirado. Intentando regenerar y reenviar una vez.")
            generate_jwt_token()
            if phishing_jwt_token:
                headers["Authorization"] = f"Bearer {phishing_jwt_token}"
                try:
                    response_retry = requests.post(PHISHING_API_URL, json=sample_data, headers=headers)
                    response_retry.raise_for_status()
                    print("Reenvío exitoso tras regenerar token.")
                    api_response_retry = response_retry.json()
                    print(f"Respuesta de la API de Phishing (tras reenvío): {json.dumps(api_response_retry, indent=2, ensure_ascii=False)}")
                    return api_response_retry
                except Exception as retry_err:
                    print(f"Error en el reenvío a Phishing API: {retry_err}")
            else:
                print("No se pudo regenerar el token para el reenvío.")
    except requests.exceptions.RequestException as req_err:
        print(f"Error de conexión al enviar la muestra a Phishing API: {req_err}")
    except json.JSONDecodeError:
        print(f"Error al decodificar la respuesta JSON de la API de Phishing. Respuesta cruda: {response.text if 'response' in locals() and hasattr(response, 'text') else 'No response object'}")
    return None

@bot.event
async def on_ready():
    global impersonator_agent
    print(f'{bot.user.name} ha iniciado sesión.')
    generate_jwt_token() # Generar token al iniciar
    impersonator_agent = create_langgraph_agent() #instancia del agente
    print("Agente impersonador cargado.")

@bot.event
async def on_message(message):
    if message.author == bot.user: # Ignorar mensajes del propio bot
        return

    print("---- Nuevo Mensaje de Discord Recibido ----")

    # Imprimir el objeto message completo en formato JSON
    # Para esto, necesitamos una forma de serializar el objeto Message de discord.py
    # No tiene un método to_dict() directo como Telethon, así que extraemos manualmente.
    # Esto será una representación simplificada, ya que el objeto Message es complejo.
    # Una serialización completa requeriría un manejo más detallado de sus atributos.
    try:
        message_attributes = {
            "id": message.id,
            "channel_id": message.channel.id,
            "guild_id": message.guild.id if message.guild else None,
            "author_id": message.author.id,
            "author_name": message.author.name,
            "author_discriminator": message.author.discriminator,
            "content": message.content,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "attachments_count": len(message.attachments),
            "embeds_count": len(message.embeds),
            "mentions_count": len(message.mentions),
            "mention_everyone": message.mention_everyone,
            "tts": message.tts,
            "pinned": message.pinned,
            "type": str(message.type),
            "reference_message_id": message.reference.message_id if message.reference else None,
            "flags": str(message.flags) # Convertir flags a string para evitar problemas de serialización
        }
        print(f"Objeto MENSAJE de Discord (JSON aproximado): \n{json.dumps(message_attributes, indent=4, default=str)}")
    except Exception as e:
        print(f"Error al serializar el mensaje de Discord a JSON: {e}")

    # Recopilar datos del mensaje en un diccionario message_data
    message_data = {}
    message_data['plataforma'] = "Discord"
    message_data['remitenteID'] = message.author.id
    message_data['nombreRemitente'] = message.author.name
    message_data['discriminadorRemitente'] = message.author.discriminator # Específico de Discord
    message_data['esBotRemitente'] = message.author.bot

    if message.guild: # Si el mensaje es de un servidor (guild)
        message_data['servidorID'] = message.guild.id
        message_data['nombreServidor'] = message.guild.name
        message_data['canalID'] = message.channel.id
        message_data['nombreCanal'] = message.channel.name
        message_data['tipoCanal'] = str(message.channel.type)
    else: # Mensaje directo (DM)
        message_data['servidorID'] = None
        message_data['nombreServidor'] = "Mensaje Directo"
        message_data['canalID'] = message.channel.id # Es el ID del DM channel
        message_data['nombreCanal'] = "Mensaje Directo con Usuario"
        message_data['tipoCanal'] = str(message.channel.type)


    message_data['contenidoMensaje'] = message.content
    
    # Timestamp
    timestamp_unix = message.created_at.timestamp()
    message_datetime_utc = message.created_at # message.created_at ya está en UTC y es timezone-aware
    message_datetime_local = message_datetime_utc.astimezone()

    message_data['timestampUnix'] = timestamp_unix
    message_data['fechaHoraUTC'] = message_datetime_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
    message_data['fechaHoraLocal'] = message_datetime_local.strftime('%Y-%m-%d %H:%M:%S %Z%z')
    message_data['idMensaje'] = message.id

    # Información de referencia (si es una respuesta)
    if message.reference and message.reference.message_id:
        message_data['esRespuesta'] = True
        message_data['mensajeReferenciadoID'] = message.reference.message_id
        # Obtener el mensaje referenciado podría requerir otra llamada async
        # try:
        #   referenced_msg = await message.channel.fetch_message(message.reference.message_id)
        #   message_data['mensajeReferenciadoContenido'] = referenced_msg.content
        #   message_data['mensajeReferenciadoAutorID'] = referenced_msg.author.id
        # except Exception as e:
        #   message_data['mensajeReferenciadoError'] = str(e)
    else:
        message_data['esRespuesta'] = False

    # Campos para el payload de la API de Phishing
    # (Adaptar según el payload esperado por la API que definimos en test_phishing_api.py)
    phishing_payload = {
        "id_user": str(message.author.id), # ID del usuario que envió el mensaje
        "id_message": str(message.id),     # ID del mensaje
        "message": message.content,        # Contenido del mensaje
        "source": "discord",               # Plataforma
        "application_version": "1.0",      # Versión de tu bot/aplicación
        "timestamp_send": int(timestamp_unix), # Timestamp Unix del envío
        "to": bot.user.name if bot.user else "DiscordBot", # Nombre del bot que recibe
        "chat_type": "guild" if message.guild else "dm", # Tipo de chat
        "id_group": str(message.guild.id) if message.guild else str(message.channel.id), # ID del servidor o DM
        "name_group": message.guild.name if message.guild else "DM with " + message.author.name, # Nombre del servidor o DM
        "message_type": "text" # Asumimos texto por ahora, podría expandirse
    }
    # Puedes añadir más campos si son necesarios para la API

    print(f"Datos del mensaje para la API (message_data): \n{json.dumps(message_data, indent=4, default=str)}")
    print(f"Payload para la API de Phishing: \n{json.dumps(phishing_payload, indent=4, default=str)}")

    # Enviar a la API de Phishing
    if message.content: # Solo enviar si hay contenido de texto
        api_response = send_to_phishing_api(phishing_payload)
        if api_response:
            print("Respuesta de la API de Phishing recibida y procesada.")
            # Extraer y enviar la respuesta técnica de la API de phishing
            try:
                technical_text = api_response.get("bot_responses", {}).get("technical_response", {}).get("text")
                if technical_text:
                    print(f"Enviando respuesta técnica de la API de Phishing: {technical_text}")
                    try:
                        await message.channel.send(f"Alerta de Seguridad: {technical_text}") # Se envía al canal
                    except Exception as send_err:
                        print(f"Error al enviar la respuesta técnica al canal de Discord: {send_err}")
                else:
                    print("No se encontró 'text' en bot_responses.technical_response de la API de Phishing.")
            except Exception as e:
                print(f"Error al procesar o enviar la respuesta técnica de la API de Phishing: {e}")
        else:
            print("No se obtuvo respuesta de la API de Phishing o hubo un error.")
    else:
        print("Mensaje sin contenido de texto, no se envía a la API de phishing.")

    # Procesar mensaje con el agente impersonador
    if impersonator_agent and message.content:
        print(f"Enviando al agente impersonador: '{message.content}'")
        try:
            agent_response = await impersonator_agent.invoke({"input": message.content})
            if agent_response and "output" in agent_response:
                print(f"Respuesta del agente: '{agent_response['output']}'")
                try:
                    await message.channel.send(agent_response['output'])
                except Exception as send_err:
                    print(f"Error al enviar la respuesta del agente al canal de Discord: {send_err}")
            else:
                print("El agente no devolvió una respuesta válida.")
        except Exception as e:
            print(f"Error al invocar el agente impersonador: {e}")
    elif not message.content:
        print("Mensaje sin contenido, no se procesa con el agente impersonador.")

    # Ya no se procesan comandos con prefijo de la misma manera
    # await bot.process_commands(message) # <--- Eliminado o comentado

if DISCORD_TOKEN is None:
    print("Error: No se encontró el DISCORD_TOKEN en las variables de entorno.")
    print("Asegúrate de haber creado un archivo .env con DISCORD_TOKEN='tu_token_aqui'")
    print("Y también las variables para la API de Phishing: PHISHING_API_USER, PHISHING_API_PASSWORD, TOKEN_URL, PHISHING_API_URL")
else:
    bot.run(DISCORD_TOKEN)