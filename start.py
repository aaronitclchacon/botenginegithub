import streamlit as st
import subprocess
import os
import sys
import time
import psutil
import shutil
import json

# --- Constantes y Rutas ---
script_dir = os.path.dirname(os.path.abspath(__file__))
# DATA_PATH será el directorio raíz para todos los datos persistentes (sesiones, configs, etc.)
# Si la variable de entorno no está, usa el directorio del script como fallback para desarrollo local.
DATA_PATH = os.getenv("DATA_PATH", script_dir)
BOTS_DIR = os.path.join(script_dir, "bots")
SESSIONS_CONFIG_FILE = os.path.join(DATA_PATH, "sessions_config.json")

# Rutas de Telegram (modificadas para multisesión y DATA_PATH)
def get_telegram_session_files(session_id):
    base_name = f"_{session_id}"
    session_file_path = os.path.join(DATA_PATH, f"chatbot_session{base_name}.session")
    return {
        "need_code": os.path.join(DATA_PATH, f"telegram_needs_code{base_name}.txt"),
        "code": os.path.join(DATA_PATH, f"telegram_code{base_name}.txt"),
        "auth_status": os.path.join(DATA_PATH, f"telegram_auth_status{base_name}.txt"),
        "error": os.path.join(DATA_PATH, f"telegram_error{base_name}.txt"),
        "session": session_file_path,
        "journal": f"{session_file_path}-journal"
    }

AUTH_CONNECTED = "connected"
AUTH_AUTHENTICATED = "authenticated"

# Rutas de WhatsApp (modificadas para multisesión y DATA_PATH)
def get_whatsapp_auth_status_file(session_id):
    return os.path.join(DATA_PATH, f"whatsapp_auth_status_{session_id}.txt")

def get_whatsapp_qr_data_url_file(session_id):
    return os.path.join(DATA_PATH, f"whatsapp_qr_data_url_{session_id}.txt")

def get_whatsapp_session_dir(session_id):
    # Corregido: La sesión se guarda directamente en DATA_PATH, no en una subcarpeta .wwebjs_auth
    return os.path.join(DATA_PATH, f"session-{session_id}")


# --- Funciones de Gestión de Configuración de Sesiones ---
def load_sessions_config():
    """Carga la configuración de las sesiones desde el archivo JSON."""
    if not os.path.exists(SESSIONS_CONFIG_FILE):
        return {}
    with open(SESSIONS_CONFIG_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_sessions_config(config):
    """Guarda la configuración de las sesiones en el archivo JSON."""
    with open(SESSIONS_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)


# --- Funciones de Detección de Sesiones ---
def discover_sessions():
    """Escanea el directorio de datos en busca de sesiones existentes y las carga en el estado."""
    # WhatsApp
    # Corregido: Buscar directamente en DATA_PATH las carpetas de sesión.
    if os.path.isdir(DATA_PATH):
        for item in os.listdir(DATA_PATH):
            full_path = os.path.join(DATA_PATH, item)
            if os.path.isdir(full_path) and item.startswith("session-"):
                session_id = item.replace("session-", "")
                if session_id not in st.session_state.whatsapp_sessions:
                    st.session_state.whatsapp_sessions[session_id] = {"running": False}
    
    # Telegram
    sessions_config = load_sessions_config()
    for item in os.listdir(DATA_PATH):
        if item.startswith("chatbot_session_") and item.endswith(".session"):
            session_id = item.replace("chatbot_session_", "").replace(".session", "")
            if session_id not in st.session_state.telegram_sessions:
                 phone = sessions_config.get("telegram", {}).get(session_id, {}).get("phone", "")
                 st.session_state.telegram_sessions[session_id] = {"running": False, "phone": phone}


# --- Funciones de Utilidad ---

def kill_process(pid):
    """Mata un proceso y sus hijos por su PID."""
    if not pid or not psutil.pid_exists(pid):
        return
    try:
        process = psutil.Process(pid)
        for child in process.children(recursive=True):
            child.kill()
        process.kill()
        st.info(f"Proceso con PID {pid} detenido.")
    except psutil.NoSuchProcess:
        pass # El proceso ya no existía
    except Exception as e:
        st.warning(f"No se pudo detener el proceso con PID {pid}: {e}")

# --- Funciones de Telegram (modificadas para multisesión) ---

def check_telegram_auth_completed(session_id):
    auth_file = get_telegram_session_files(session_id)["auth_status"]
    if not os.path.exists(auth_file):
        return None
    with open(auth_file, "r") as f:
        return f.read().strip()

def check_telegram_needs_code(session_id):
    return os.path.exists(get_telegram_session_files(session_id)["need_code"])

def get_telegram_error(session_id):
    error_file = get_telegram_session_files(session_id)["error"]
    if os.path.exists(error_file):
        with open(error_file, "r") as f:
            return f.read().strip()
    return None

def start_telegram_bot(session_id, phone, key, api_id, api_hash):
    if st.session_state.telegram_sessions.get(session_id, {}).get("pid"):
        kill_process(st.session_state.telegram_sessions[session_id]["pid"])

    # Guardar/Actualizar el número de teléfono en la configuración
    config = load_sessions_config()
    if "telegram" not in config:
        config["telegram"] = {}
    config["telegram"][session_id] = {"phone": phone}
    save_sessions_config(config)

    telegram_env = os.environ.copy()
    telegram_env.update({
        "PHONE_NUMBER": phone, 
        "OPENAI_API_KEY": key, 
        "API_ID": api_id, 
        "API_HASH": api_hash,
        "SESSION_ID": session_id,
        "PYTHONUNBUFFERED": "1"
    })
    process = subprocess.Popen([sys.executable, os.path.join(BOTS_DIR, "telegram.py")], env=telegram_env)
    
    st.session_state.telegram_sessions[session_id] = {
        "pid": process.pid,
        "running": True,
        "phone": phone
    }
    st.info(f"Iniciando sesión de Telegram '{session_id}' con PID: {process.pid}")

def clear_telegram_auth(session_id):
    files_to_delete = get_telegram_session_files(session_id).values()
    for f in files_to_delete:
        if os.path.exists(f):
            os.remove(f)
    
    # Eliminar de la configuración
    config = load_sessions_config()
    if config.get("telegram", {}).get(session_id):
        del config["telegram"][session_id]
        save_sessions_config(config)

    st.info(f"Sesión de Telegram '{session_id}' limpiada.")


# --- Funciones de WhatsApp (modificadas para multisesión) ---

def check_whatsapp_auth_completed(session_id):
    auth_file = get_whatsapp_auth_status_file(session_id)
    if not os.path.exists(auth_file):
        return None
    with open(auth_file, "r") as f:
        return f.read().strip()

def get_whatsapp_qr_data_url(session_id):
    qr_file = get_whatsapp_qr_data_url_file(session_id)
    if os.path.exists(qr_file):
        with open(qr_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def start_whatsapp_bot(session_id, key, email):
    # Asegurarse de que no haya otro proceso con el mismo session_id
    if st.session_state.whatsapp_sessions.get(session_id, {}).get("pid"):
        kill_process(st.session_state.whatsapp_sessions[session_id]["pid"])

    whatsapp_env = os.environ.copy()
    whatsapp_env.update({
        "OPENAI_API_KEY": key,
        "SESSION_ID": session_id,
        "PYTHONUNBUFFERED": "1"
    })
    if email:
        whatsapp_env["WHATSAPP_QR_EMAIL"] = email
    if os.getenv("PUPPETEER_EXECUTABLE_PATH"):
        whatsapp_env["PUPPETEER_EXECUTABLE_PATH"] = os.getenv("PUPPETEER_EXECUTABLE_PATH")
    
    process = subprocess.Popen(["node", os.path.join(BOTS_DIR, "whatsapp.js")], env=whatsapp_env)
    
    st.session_state.whatsapp_sessions[session_id] = {
        "pid": process.pid,
        "running": True,
        "email": email
    }
    st.info(f"Iniciando sesión de WhatsApp '{session_id}' con PID: {process.pid}")

def clear_whatsapp_auth(session_id):
    auth_status_file = get_whatsapp_auth_status_file(session_id)
    qr_file = get_whatsapp_qr_data_url_file(session_id)
    session_dir = get_whatsapp_session_dir(session_id)

    if os.path.exists(auth_status_file): os.remove(auth_status_file)
    if os.path.exists(qr_file): os.remove(qr_file)
    if os.path.isdir(session_dir): shutil.rmtree(session_dir)
    st.info(f"Sesión de WhatsApp '{session_id}' limpiada.")


# --- Interfaz de Streamlit ---

st.set_page_config(page_title="BotEngine Control 🤖", layout="wide", page_icon=":robot_face:")
st.title("Panel de Control de BotEngine 🤖 ")

# Inicializar estado de sesión
if 'telegram_sessions' not in st.session_state: st.session_state.telegram_sessions = {}
if 'whatsapp_sessions' not in st.session_state: st.session_state.whatsapp_sessions = {}
if 'sessions_discovered' not in st.session_state:
    discover_sessions()
    st.session_state.sessions_discovered = True


# --- Credenciales Globales ---
st.subheader("🔑 API Keys")
openai_api_key = st.text_input("OpenAI API Key", value=os.getenv("OPENAI_API_KEY", ""), type="password")

with st.expander("Credenciales de Telegram (requerido para el bot de Telegram)"):
    api_id = st.text_input("Telegram API ID", value=os.getenv("API_ID", ""))
    api_hash = st.text_input("Telegram API Hash", value=os.getenv("API_HASH", ""), type="password")

st.markdown("---")

# --- Panel de WhatsApp ---
st.subheader("🟢 WhatsApp (Multisesión)")

# Crear nueva sesión
with st.expander("Añadir Nueva Sesión de WhatsApp"):
    new_session_id = st.text_input("Nombre de la nueva sesión (ej: cliente_A)", key="wa_new_session_name")
    new_session_email = st.text_input("Enviar QR a (email, opcional)", key="wa_new_session_email")
    
    if st.button("Iniciar Nueva Sesión", key="start_new_whatsapp"):
        if not new_session_id:
            st.error("El nombre de la sesión no puede estar vacío.")
        elif new_session_id in st.session_state.whatsapp_sessions and st.session_state.whatsapp_sessions[new_session_id].get("running"):
            st.warning(f"La sesión '{new_session_id}' ya está en ejecución.")
        elif not openai_api_key:
            st.error("Por favor, introduce la OpenAI API Key.")
        else:
            start_whatsapp_bot(new_session_id, openai_api_key, new_session_email)
            st.rerun()

st.markdown("### Sesiones de WhatsApp Activas")

if not st.session_state.whatsapp_sessions:
    st.info("No hay sesiones de WhatsApp activas. Añade una para empezar.")
else:
    # Mostrar cada sesión en una columna
    cols = st.columns(len(st.session_state.whatsapp_sessions))
    session_ids = list(st.session_state.whatsapp_sessions.keys())

    for i, session_id in enumerate(session_ids):
        with cols[i]:
            session_data = st.session_state.whatsapp_sessions[session_id]
            st.markdown(f"**Sesión: `{session_id}`**")
            
            if session_data.get("running"):
                # --- Botones de control para sesiones en ejecución ---
                # Se muestran siempre primero para poder cancelar en cualquier fase.
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"Detener", key=f"stop_wa_{session_id}"):
                        kill_process(session_data.get("pid"))
                        st.session_state.whatsapp_sessions[session_id]["running"] = False
                        st.rerun()
                with col2:
                    if st.button(f"Limpiar", key=f"clear_wa_{session_id}"):
                        kill_process(session_data.get("pid"))
                        clear_whatsapp_auth(session_id)
                        del st.session_state.whatsapp_sessions[session_id]
                        st.rerun()

                # --- Visualización de estado ---
                auth_status = check_whatsapp_auth_completed(session_id)
                if auth_status == AUTH_AUTHENTICATED:
                    st.success("✅ Listo y operativo.")
                elif auth_status == AUTH_CONNECTED:
                    st.info("🤖 Conectado, cargando agente...")
                    time.sleep(3)
                    st.rerun()
                else:
                    qr_url = get_whatsapp_qr_data_url(session_id)
                    if qr_url:
                        st.image(qr_url, caption=f"Escanea para conectar '{session_id}'")
                    else:
                        st.info("Iniciando y esperando QR...")
                    time.sleep(3) # Dar tiempo a que el QR se genere
                    st.rerun()

            else:
                st.warning("Sesión detenida.")
                email = session_data.get("email", "")
                if st.button("Reiniciar Sesión", key=f"restart_wa_{session_id}"):
                     if not openai_api_key:
                        st.error("Por favor, introduce la OpenAI API Key.")
                     else:
                        start_whatsapp_bot(session_id, openai_api_key, email)
                        st.rerun()



st.markdown("---")

# --- Panel de Telegram ---
st.subheader("🔵 Telegram (Multisesión)")

# Crear nueva sesión
with st.expander("Añadir Nueva Sesión de Telegram"):
    new_tg_session_id = st.text_input("Nombre de la nueva sesión", key="tg_new_session_name")
    new_tg_phone = st.text_input("Número de Teléfono (con código de país)", key="tg_new_phone")
    
    if st.button("Iniciar Nueva Sesión de Telegram", key="start_new_telegram"):
        if not new_tg_session_id:
            st.error("El nombre de la sesión no puede estar vacío.")
        elif new_tg_session_id in st.session_state.telegram_sessions and st.session_state.telegram_sessions[new_tg_session_id].get("running"):
            st.warning(f"La sesión '{new_tg_session_id}' ya está en ejecución.")
        elif not all([openai_api_key, new_tg_phone, api_id, api_hash]):
            st.error("Para iniciar, se requieren API Key, Teléfono, API ID y API Hash.")
        else:
            start_telegram_bot(new_tg_session_id, new_tg_phone, openai_api_key, api_id, api_hash)
            st.rerun()

st.markdown("### Sesiones de Telegram Activas")

if not st.session_state.telegram_sessions:
    st.info("No hay sesiones de Telegram activas. Añade una para empezar.")
else:
    cols_tg = st.columns(len(st.session_state.telegram_sessions))
    session_ids_tg = list(st.session_state.telegram_sessions.keys())

    for i, session_id in enumerate(session_ids_tg):
        with cols_tg[i]:
            session_data = st.session_state.telegram_sessions[session_id]
            st.markdown(f"**Sesión: `{session_id}`**")
            st.markdown(f"Teléfono: `{session_data.get('phone')}`")
            
            if session_data.get("running"):
                # --- Botones de control para sesiones en ejecución ---
                col1_tg, col2_tg = st.columns(2)
                with col1_tg:
                    if st.button("Detener", key=f"stop_tg_{session_id}"):
                        kill_process(session_data.get("pid"))
                        st.session_state.telegram_sessions[session_id]["running"] = False
                        st.rerun()
                with col2_tg:
                    if st.button("Limpiar", key=f"clear_tg_{session_id}"):
                        kill_process(session_data.get("pid"))
                        clear_telegram_auth(session_id)
                        del st.session_state.telegram_sessions[session_id]
                        st.rerun()

                # --- Visualización de estado ---
                error = get_telegram_error(session_id)
                auth_status = check_telegram_auth_completed(session_id)
                if error:
                    st.error(f"❌ Error: {error}")
                elif auth_status == AUTH_AUTHENTICATED:
                    st.success("✅ Listo y operativo.")
                elif auth_status == AUTH_CONNECTED:
                    st.info("🤖 Conectado, cargando agente...")
                    time.sleep(3)
                    st.rerun()
                elif check_telegram_needs_code(session_id):
                    st.warning("📱 Se necesita código.")
                    code = st.text_input("Introduce el código", key=f"tg_code_{session_id}")
                    if st.button("Enviar Código", key=f"submit_tg_code_{session_id}"):
                        code_file = get_telegram_session_files(session_id)["code"]
                        with open(code_file, "w") as f:
                            f.write(code)
                        st.info("Código enviado...")
                        time.sleep(5)
                        st.rerun()
                else:
                    st.info("Iniciando y conectando...")
                    time.sleep(3)
                    st.rerun()

            else:
                st.warning("Sesión detenida.")
                phone = session_data.get("phone", "")
                if st.button("Reiniciar Sesión", key=f"restart_tg_{session_id}"):
                    phone = session_data.get("phone", "")
                    if not phone:
                        st.error("No se encontró el número de teléfono. Por favor, elimine y vuelva a crear la sesión.")
                    elif not all([openai_api_key, phone, api_id, api_hash]):
                        st.error("Faltan credenciales globales para reiniciar (API Key, API ID/Hash).")
                    else:
                        start_telegram_bot(session_id, phone, openai_api_key, api_id, api_hash)
                        st.rerun()