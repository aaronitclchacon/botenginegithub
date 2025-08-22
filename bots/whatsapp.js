// Importa las librerías necesarias
const qrcode = require('qrcode');
const { Client, LocalAuth } = require('whatsapp-web.js');
const fs = require('fs');
const fsPromises = fs.promises;
const path = require('path');
const axios = require('axios');
const FormData = require('form-data');
const { createLangGraphAgent } = require('../langgraph/agente_impersonador_wa');
const nodemailer = require('nodemailer');

// Cargar .env desde la raíz del proyecto
require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

// --- ID de Sesión y Rutas de Datos ---
const SESSION_ID = process.env.SESSION_ID || 'default_session';
// Usar DATA_PATH si está definida, si no, usar el directorio del proyecto como base.
const DATA_PATH = process.env.DATA_PATH || path.resolve(__dirname, '../..');
console.log(`[whatsapp.js] Iniciando sesión con ID: ${SESSION_ID}`);
console.log(`[whatsapp.js] Usando DATA_PATH: ${DATA_PATH}`);


// --- Constantes y Rutas para Streamlit ---
const AUTH_STATUS_FILE = path.join(DATA_PATH, `whatsapp_auth_status_${SESSION_ID}.txt`);
const QR_DATA_URL_FILE = path.join(DATA_PATH, `whatsapp_qr_data_url_${SESSION_ID}.txt`);
const AUTH_CONNECTED = 'connected';
const AUTH_AUTHENTICATED = 'authenticated';

// --- Configuración de Email ---
const WHATSAPP_QR_EMAIL = process.env.WHATSAPP_QR_EMAIL;
const EMAIL_HOST = process.env.EMAIL_HOST;
const EMAIL_PORT = process.env.EMAIL_PORT;
const EMAIL_USER = process.env.EMAIL_USER;
const EMAIL_PASS = process.env.EMAIL_PASS;

let mailTransporter;
if (EMAIL_HOST && EMAIL_PORT && EMAIL_USER && EMAIL_PASS) {
    mailTransporter = nodemailer.createTransport({
        host: EMAIL_HOST,
        port: EMAIL_PORT,
        secure: EMAIL_PORT === '465', // true for 465, false for other ports
        auth: {
            user: EMAIL_USER,
            pass: EMAIL_PASS,
        },
    });
    console.log("[whatsapp.js] Transportador de correo configurado.");
} else {
    console.warn("[whatsapp.js] Faltan variables de entorno para la configuración del email. El envío de QR por correo estará deshabilitado.");
}


// --- Credenciales y URLs API Phishing ---
const PHISHING_API_USER = process.env.PHISHING_API_USER;
const PHISHING_API_PASSWORD = process.env.PHISHING_API_PASSWORD;
const TOKEN_URL = process.env.TOKEN_URL;
const PHISHING_API_URL = process.env.PHISHING_API_URL;

if (!PHISHING_API_USER || !PHISHING_API_PASSWORD || !TOKEN_URL || !PHISHING_API_URL) {
    console.error("Error: Faltan variables de entorno para la API de Phishing.");
}

// --- Variables Globales ---
let phishingJwtToken = null;
let compiledGraph;

// --- Cliente de WhatsApp ---
console.log("[whatsapp.js] Creando cliente de WhatsApp...");
const whatsapp = new Client({
    authStrategy: new LocalAuth({
        clientId: SESSION_ID,
        dataPath: DATA_PATH // Especificar el directorio raíz para las sesiones
    }),
    puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH,
    }
});
console.log("[whatsapp.js] Cliente de WhatsApp creado.");

// --- Lógica de Autenticación y QR para Streamlit ---
async function isAuthenticated() {
    try {
        const status = (await fsPromises.readFile(AUTH_STATUS_FILE, 'utf-8')).trim();
        return status === AUTH_AUTHENTICATED || status === AUTH_CONNECTED;
    } catch {
        return false;
    }
}

whatsapp.on('qr', async (qr) => {
    if (!(await isAuthenticated())) {
        console.log('Generando código QR como URL de datos para Streamlit...');
        try {
            const qrDataURL = await qrcode.toDataURL(qr);
            await fsPromises.writeFile(QR_DATA_URL_FILE, qrDataURL, 'utf-8');
            console.log('Código QR (URL de datos) guardado.');

            // Enviar el QR por correo si está configurado
            if (WHATSAPP_QR_EMAIL && mailTransporter) {
                await sendQrByEmail(WHATSAPP_QR_EMAIL, qrDataURL);
            }

        } catch (error) {
            console.error('Error al generar o enviar el código QR:', error);
        }
    }
});

whatsapp.on('authenticated', async () => {
    console.log('[whatsapp.js] Cliente autenticado. Escribiendo estado CONECTADO.');
    try {
        await fsPromises.writeFile(AUTH_STATUS_FILE, AUTH_CONNECTED);
        await fsPromises.unlink(QR_DATA_URL_FILE).catch(() => {});
    } catch (error) {
        console.error('[whatsapp.js] Error al guardar el estado de conexión:', error);
    }
});

whatsapp.on('ready', async () => {
    console.log('🤖 BotEngine activo en WhatsApp... esperando mensajes');
    
    console.log("[whatsapp.js] Creando agente LangGraph...");
    ({ compiledGraph } = createLangGraphAgent());
    console.log("[whatsapp.js] Agente LangGraph creado.");

    generateJwtToken();

    try {
        await fsPromises.writeFile(AUTH_STATUS_FILE, AUTH_AUTHENTICATED);
        console.log('[whatsapp.js] Estado AUTENTICADO para Streamlit guardado.');
    } catch (error) {
        console.error('[whatsapp.js] Error al guardar el estado de autenticación final:', error);
    }
});

//fecha y hora
const tz = 'Europe/Madrid';
const fechaHora = new Intl.DateTimeFormat('es-ES', {
  timeZone: tz,
  day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit'
}).format(new Date());

const subject = `Código QR para conectar tu WhatsApp a BotEngine ${fechaHora}`;

// --- Función para Enviar Email con QR ---
async function sendQrByEmail(recipient, qrDataURL) {
    if (!mailTransporter) {
        console.warn("El transportador de correo no está configurado, no se puede enviar el email.");
        return;
    }

    const base64 = qrDataURL.split(',')[1]; 
    const mailOptions = {
        from: `"BotEngine" <${EMAIL_USER}>`,
        to: recipient,
        subject,
        html: `
            <p>Hola,</p>
            <p>Escanea el siguiente código QR con tu aplicación de WhatsApp para conectar tu cuenta a BotEngine.</p>
            <p>Este código se actualiza periódicamente. Si no funciona, espera a recibir el siguiente.</p>
            <img src="cid:whatsapp-qr" alt="Código QR de WhatsApp" width="220" height="220" />
            <br/>
            <p>Gracias,<br/>El equipo de BotEngine</p>
        `,
        attachments: [
            {
                filename: 'whatsapp-qr.png',
                content: base64,
                encoding: 'base64',
                contentType: 'image/png',
                cid: 'whatsapp-qr' // Mismo cid que en el src de la imagen
            }
        ],
        // Opcional: más señales anti-hilo para Gmail
  headers: {
    'X-Entity-Ref-ID': String(Date.now())   // identificador único por envío
  }
    };

    try {
        await mailTransporter.sendMail(mailOptions);
        console.log(`Código QR enviado exitosamente a ${recipient}`);
    } catch (error) {
        console.error(`Error al enviar el email a ${recipient}:`, error);
    }
}


// --- Funciones para la API de Phishing (tu código) ---
async function generateJwtToken() {
    console.log(`Generando token JWT desde: ${TOKEN_URL}`);
    const payload = { username: PHISHING_API_USER, password: PHISHING_API_PASSWORD };
    try {
        const response = await axios.post(TOKEN_URL, payload);
        if (response.data && response.data.access) {
            console.log("Token de ACCESO JWT generado exitosamente.");
            phishingJwtToken = response.data.access;
        } else {
            console.error("Error: El campo 'access' no se encontró en la respuesta del token.", response.data);
            phishingJwtToken = null;
        }
    } catch (error) {
        const errorMessage = error.response ? JSON.stringify(error.response.data) : error.message;
        console.error(`Error HTTP al generar token: ${error.message} - Respuesta: ${errorMessage}`);
        phishingJwtToken = null;
    }
}

async function sendToPhishingApi(sampleData) {
    if (!phishingJwtToken) {
        console.warn("Token JWT no disponible. Intentando generar uno nuevo.");
        await generateJwtToken();
        if (!phishingJwtToken) {
            console.error("Fallo al generar nuevo token. No se enviará la muestra.");
            return { error: "Fallo al generar token para API Phishing" };
        }
    }

    const attachments = sampleData.sample?.message_content?.attachments || [];

    try {
        const headers = { "Authorization": `Bearer ${phishingJwtToken}` };
        let response;

        if (attachments.length > 0) {
            console.log("Detectados adjuntos. Preparando envío multipart/form-data.");
            
            // 1. Crear una copia limpia del payload sin las rutas de archivo locales
            const sanitizedSampleData = JSON.parse(JSON.stringify(sampleData));
            if (sanitizedSampleData.sample?.message_content?.attachments) {
                 sanitizedSampleData.sample.message_content.attachments.forEach(att => delete att.file_path);
            }

            // 2. Preparar el FormData
            const formData = new FormData();
            formData.append('sample', JSON.stringify(sanitizedSampleData), { contentType: 'application/json' });

            // 3. Adjuntar cada archivo físico
            for (const attachment of attachments) {
                if (attachment.file_path && fs.existsSync(attachment.file_path)) {
                    formData.append(
                        'attachments',
                        fs.createReadStream(attachment.file_path),
                        {
                            filename: attachment.filename,
                            contentType: attachment.mime_type || 'application/octet-stream'
                        }
                    );
                }
            }

            // 4. Enviar con archivos
            response = await axios.post(PHISHING_API_URL, formData, {
                headers: {
                    ...headers,
                    ...formData.getHeaders()
                }
            });
        } else {
            // Envío JSON normal sin archivos
            headers["Content-Type"] = "application/json";
            response = await axios.post(PHISHING_API_URL, sampleData, { headers });
        }

        console.log("Muestra enviada exitosamente a la API de Phishing.");
        return response.data;

    } catch (error) {
        if (error.response?.status === 401) {
            console.info("Token posiblemente expirado. Regenerando y reenviando.");
            await generateJwtToken();
            if (phishingJwtToken) {
                return sendToPhishingApi(sampleData); // Reintentar con nuevo token
            }
        }
        console.error(`Error al enviar la muestra a Phishing API: ${error.message}`);
        return { error: `Error al enviar a API Phishing: ${error.message}` };
    } finally {
        // Limpiar archivos temporales en cualquier caso (éxito o error)
        for (const attachment of attachments) {
            if (attachment.file_path && fs.existsSync(attachment.file_path)) {
                try {
                    await fsPromises.unlink(attachment.file_path);
                    console.log(`Archivo temporal eliminado: ${attachment.file_path}`);
                } catch (unlinkError) {
                    console.error(`Error al eliminar archivo temporal: ${unlinkError}`);
                }
            }
        }
    }
}


// --- Manejo de Mensajes (tu código con adaptaciones) ---
whatsapp.on('message', async msg => {
    if (msg.fromMe) return;

    const messageData = {};
    console.log('--- Nuevo Mensaje Recibido ---');

    // --- EXTRAER DATOS DEL MENSAJE ---
    const senderId = msg.from;
    messageData.remitenteID = senderId;
    const userMessage = msg.body;
    messageData.contenidoMensaje = userMessage;
    const chat = await msg.getChat();
    const isGroup = chat.isGroup;
    messageData.esUnGrupo = isGroup;
    const contact = await msg.getContact();
    const senderName = contact.pushname || contact.displayName || contact.name || 'Desconocido';
    messageData.nombreRemitente = senderName;
    const messageId = msg.id && msg.id._serialized ? msg.id._serialized : 'No disponible';
    messageData.idMensaje = messageId;

    // --- Procesar Archivos Adjuntos ---
    const attachments = [];
    let mediaType = "text";
    let mimeType = null;

    if (msg.hasMedia) {
        try {
            const media = await msg.downloadMedia();
            if (media) {
                // Crear directorio temporal dentro de DATA_PATH si no existe
                const tempDir = path.join(DATA_PATH, 'temp_media');
                await fsPromises.mkdir(tempDir, { recursive: true });

                // Generar nombre único para el archivo
                const timestamp = new Date().toISOString().replace(/[:.]/g, '');
                const fileExt = media.mimetype ? media.mimetype.split('/')[1] : 'bin';
                const fileName = `whatsapp_${messageId}_${timestamp}.${fileExt}`;
                const filePath = path.join(tempDir, fileName);

                // Guardar el archivo
                const mediaBuffer = Buffer.from(media.data, 'base64');
                await fsPromises.writeFile(filePath, mediaBuffer);

                // Determinar tipo de archivo basado en mimetype
                mimeType = media.mimetype;
                if (mimeType) {
                    if (mimeType.startsWith('audio/') || mimeType === 'application/ogg') {
                        mediaType = "audio";
                    } else if (mimeType.startsWith('image/')) {
                        mediaType = "image";
                    } else if (mimeType.startsWith('video/')) {
                        mediaType = "video";
                    } else {
                        mediaType = "document";
                    }
                } else {
                    mediaType = "document";
                }

                // Crear datos del adjunto
                const attachment = {
                    type: mediaType,
                    filename: fileName,
                    size: mediaBuffer.length,
                    mime_type: mimeType || "application/octet-stream",
                    file_path: filePath
                };
                attachments.push(attachment);
                console.log('Archivo adjunto procesado:', attachment);
            }
        } catch (error) {
            console.error('Error al procesar archivo adjunto:', error);
        }
    }

    messageData.tipoMensaje = mediaType;
    messageData.mimeType = mimeType;

    // --- Construir Payload y Enviar a API Phishing ---
    const phishingPayload = {
        sample: {
            message_id: messageId,
            platform: "whatsapp",
            chat_type: isGroup ? "group" : "private",
            from: senderName,
            to: whatsapp.info ? (whatsapp.info.pushname || whatsapp.info.wid.user) : "BotEngine",
            notifyName: senderName,
            sender_info: {
                user_id: senderId,
                username: "N/A",
                is_bot: msg.author ? 1 : 0
            },
            message_content: {
                text: userMessage,
                entities: [],
                attachments: attachments
            },
            timestamp: msg.timestamp ? new Date(msg.timestamp * 1000).toISOString() : new Date().toISOString(),
            context: {}
        }
    };
    
    console.log('\n--- Payload para API Phishing ---');
    console.log(JSON.stringify(phishingPayload, null, 2));

    const phishingApiResponse = await sendToPhishingApi(phishingPayload);
    messageData.phishingApiResponse = phishingApiResponse || { error: "No se obtuvo respuesta" };
    
    if (phishingApiResponse && phishingApiResponse.bot_responses?.technical_response?.text) {
        const technicalText = phishingApiResponse.bot_responses.technical_response.text;
        console.log(`Enviando respuesta técnica: ${technicalText}`);
        await whatsapp.sendMessage(msg.from, `Alerta de Seguridad: ${technicalText}`);
    }

    // --- Interacción con el Agente Conversacional ---
    if (compiledGraph) {
        try {
            const result = await compiledGraph.invoke(
                { input: userMessage },
                { configurable: { thread_id: senderId } }
            );
            const reply = result.output;
            messageData.respuestaBot = reply;
            await msg.reply(reply);
            console.log(`Respuesta del agente enviada a ${senderName}: ${reply}`);
        } catch (error) {
            console.error(`Error al generar respuesta del agente para ${senderName}: ${error}`);
            await msg.reply('Tuve un problema al procesar tu mensaje.');
        }
    }

    console.log('\n--- Datos del Mensaje en JSON ---');
    console.log(JSON.stringify(messageData, null, 2));
    console.log('--- Fin del Procesamiento de Mensaje ---');
});

// --- Inicialización y Manejo de Errores ---
process.on('unhandledRejection', (reason, promise) => {
  console.error('[whatsapp.js] ERROR: Unhandled Rejection at:', promise, 'reason:', reason);
});

console.log("[whatsapp.js] Inicializando cliente de WhatsApp...");
whatsapp.initialize().catch(err => {
    console.error('[whatsapp.js] ERROR: La inicialización del cliente falló:', err);
});