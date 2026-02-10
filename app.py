import streamlit as st
import cv2
import numpy as np
import pandas as pd
from datetime import datetime
import PIL.Image
import serial
import serial.tools.list_ports
import time
import io
import requests # Para descargar la imagen y mostrarla en pantalla si es URL

# --- IMPORTACIÓN DE MÓDULOS PROPIOS ---
try:
    from ai_services import consultar_gemini, consultar_azure
    from db_services import init_db, guardar_registro, obtener_historial, obtener_imagen_por_id
except ImportError as e:
    st.error(f" Error crítico: Faltan archivos del proyecto ({e}).")
    st.stop()
# --- IMPORTACIÓN DEL DETECTOR DE GESTOS  ---
try:
    from captura_gesto1 import DetectorGestos
except ImportError:
    DetectorGestos = None # Manejo suave si falta el archivo

# ==========================================
#  CONFIGURACIÓN INICIAL
# ==========================================
st.set_page_config(page_title="Proyecto D.A.R.", page_icon="🧊", layout="wide")

# Inicializar Base de Datos (Crea el archivo si no existe)
init_db()

st.title(" Detector de tristeza automática con IA ")
st.subheader("Sistema de Mitigación de Tristeza")

if 'ultimo_analisis' not in st.session_state:
    st.session_state.ultimo_analisis = None
# Variables para el control de gestos
if 'conteo_activo' not in st.session_state:
    st.session_state.conteo_activo = False
if 'inicio_conteo' not in st.session_state:
    st.session_state.inicio_conteo = 0
if 'foto_gesto_capturada' not in st.session_state:
    st.session_state.foto_gesto_capturada = None

# ==========================================
#  UTILIDADES
# ==========================================
def convertir_link_drive(url):
    """
    Convierte un enlace de vista de Google Drive en un enlace de descarga directa
    que Azure pueda leer.
    """
    if "drive.google.com" in url and "/view" in url:
        # Extraer ID
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except:
            return url
    return url

def descargar_imagen_url(url):
    """Descarga la imagen para mostrarla en Streamlit"""
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return np.array(PIL.Image.open(io.BytesIO(resp.content)))
    except:
        return None
    return None

# ==========================================
#  GESTIÓN HARDWARE
# ==========================================
def enviar_comando_esp32(destino, es_wifi=False):
    """
    Envía el comando de dispensado.
    :param destino: Puerto COM (str) o URL HTTP (str)
    :param es_wifi: Booleano para decidir qué protocolo usar
    """
    if not destino or destino == "Sin Conexión":
        return False

    # --- MODO WIFI (HTTP REQUEST) ---
    if es_wifi:
        try:
            # st.toast(f"📡 Enviando petición a {destino}...", icon="📶")
            # Enviamos la petición GET
            respuesta = requests.get(destino, timeout=5)
            
            # Si el código de estado es 200 (OK)
            if respuesta.status_code == 200:
                # st.success(f"¡Éxito! Respuesta ESP32: {respuesta.text}")
                return True
            else:
                st.error(f"Error: El ESP32 respondió con código {respuesta.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            st.error("Error: El ESP32 no respondió a tiempo (Timeout).")
            return False
        except requests.exceptions.ConnectionError:
            st.error("Error: No se pudo conectar con el ESP32. Revisa la IP y el WiFi.")
            return False
        except Exception as e:
            st.error(f"Ocurrió un error WiFi inesperado: {e}")
            return False

    # --- MODO SERIAL (CABLE/SIMULACIÓN) ---
    else:
        try:
            es_simulacion = "socket://" in destino
            
            with serial.serial_for_url(destino, baudrate=115200, timeout=2) as ser:
                if not es_simulacion: 
                    # El ESP32 físico se reinicia al abrir el puerto serial (DTR reset).
                    time.sleep(2)
                
                ser.write(b'BEBIDA\n')
                return True
                
        except serial.SerialException as e:
            if "Access is denied" in str(e) or "PermissionError" in str(e):
                st.error(f"🚫 PUERTO OCUPADO: Cierra el Monitor Serial en VS Code.")
            else:
                st.error(f"Error Hardware: {e}")
            return False
        except Exception as e:
            st.error(f"Error General Hardware: {e}")
            return False
# ==========================================
#  BARRA LATERAL
# ==========================================
with st.sidebar:
    st.header("Configuración")
    
    # --- SECCIÓN HARDWARE ---
    st.subheader("🔌 Hardware Dispensador")
    
        # Selector de Tipo de Conexión
    tipo_conexion = st.radio("Método de Conexión:", ["🔌 Serial / Simulación", "📡 WiFi (HTTP)"])
    
    target_hardware = "Sin Conexión" # Variable final a usar
    usar_modo_wifi = False
    selected_port = None
    if tipo_conexion == "📡 WiFi (HTTP)":
        usar_modo_wifi = True
        # Input para la URL del ESP32
        target_hardware = st.text_input("URL del ESP32:", value="http://192.168.0.100/bebida", help="Debe incluir http:// y la ruta configurada en el ESP32")
    
    else:
        usar_modo_wifi = False
        try:
            ports = serial.tools.list_ports.comports()
            opciones_puertos = [p.device for p in ports]
        except:
            opciones_puertos = []
        
        # Agregar opciones manuales
        opciones_puertos.insert(0, "socket://localhost:4000") # Para Wokwi
        opciones_puertos.insert(0, "Sin Conexión")
        
        selected_port = st.selectbox("Puerto Conexión:", options=opciones_puertos, index=1)
        
        if st.button("🔄 Refrescar Puertos USB"):
            st.rerun()
        
        target_hardware = selected_port
    
    st.divider()
    
    # IA
    modo_operacion = st.radio("Cerebro IA:", (" Gemini (Dev)", " Azure (Prod)"))
    
    if modo_operacion == " Gemini (Dev)":
        api_key = st.text_input("Gemini API Key", type="password",value="")
        endpoint = None
        deployment_name = None
    else:
        api_key = st.text_input("Azure API Key", type="password",value="")
        endpoint = st.text_input("Azure Endpoint", value="")
        deployment_name = st.text_input("Nombre Despliegue (Model Name)", value="gpt-5-chat")

# ==========================================
#  CAPTURA Y ANÁLISIS
# ==========================================
col1, col2 = st.columns([1, 1])

with col1:
    st.write("### 1. Fuente de Imagen")
    
    fuente_entrada = st.radio(
        "Selecciona el origen:", 
        ["📸 Cámara Web","🖐️ Cámara Inteligente (Gestos)" ,"📂 Subir Archivo", "🔗 URL (Drive/Web)"], 
        horizontal=True
    )
   
    img_opencv = None    # Imagen original en formato OpenCV (BGR)
    formato_origen = "JPEG" # Valor por defecto

    # --- OBTENCIÓN DE LA IMAGEN ---
    if fuente_entrada == "📸 Cámara Web":
        img_cam = st.camera_input("Capturar")
        if img_cam:
            bytes_data = img_cam.getvalue()
            img_opencv = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            formato_origen = "PNG" # Cámara = Calidad Máxima
    # ---  CÁMARA INTELIGENTE (GESTOS) ---
    elif fuente_entrada == "🖐️ Cámara Inteligente (Gestos)":
        if DetectorGestos is None:
            st.error("⚠️ Falta 'captura_gesto.py' o 'hand_landmarker.task'.")
        else:
            iniciar_stream = st.checkbox("🔴 Activar Cámara", value=False)
            ventana_video = st.image([]) # Placeholder para el video
            texto_estado = st.empty()
            
            # Si ya tenemos una foto tomada en memoria, la usamos
            if st.session_state.foto_gesto_capturada is not None and not iniciar_stream:
                img_opencv = st.session_state.foto_gesto_capturada
                st.image(img_opencv, caption="Foto Capturada por Gesto", channels="BGR")
                formato_origen = "PNG"
                
            elif iniciar_stream:
                # Inicializar detector una sola vez en session_state
                if 'detector_gestos' not in st.session_state:
                    try:
                        with st.spinner("Cargando modelo de manos..."):
                            st.session_state.detector_gestos = DetectorGestos()
                    except Exception as e:
                        st.error(f"Error cargando modelo: {e}")
                        st.stop()

                cap = cv2.VideoCapture(0)
                stop_button = st.button("⏹️ Detener")
                
                while cap.isOpened() and not stop_button:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    frame = cv2.flip(frame, 1)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    # Detección de Gestos
                    frame_dibujado, gesto = st.session_state.detector_gestos.detectar_estado_mano(frame_rgb.copy())
                    
                    # Lógica del Temporizador
                    if gesto == "PALMA" and not st.session_state.conteo_activo:
                        st.session_state.conteo_activo = True
                        st.session_state.inicio_conteo = time.time()
                    
                    elif gesto == "PUNO" and st.session_state.conteo_activo:
                        st.session_state.conteo_activo = False
                        texto_estado.warning("⏹️ Cancelado")
                    
                    # Renderizar conteo
                    if st.session_state.conteo_activo:
                        restante = 5 - int(time.time() - st.session_state.inicio_conteo)
                        
                        if restante > 0:
                            # Dibujar número en el video
                            cv2.putText(frame_dibujado, str(restante), (50, 150), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 255), 8)
                            texto_estado.info(f"📸 TOMANDO FOTO EN {restante}...")
                        else:
                            # TIEMPO CUMPLIDO: FOTO
                            texto_estado.success("📸 ¡CAPTURA!")
                            # Guardamos la imagen limpia (frame original en BGR)
                            st.session_state.foto_gesto_capturada = frame 
                            st.session_state.conteo_activo = False
                            img_opencv = frame # Asignamos para que se procese abajo
                            formato_origen = "PNG"
                            cap.release()
                            st.rerun() # Recargamos para mostrar el botón de analizar
                            break
                    
                    # Convertir a RGB para mostrar en Streamlit
                    frame_show = cv2.cvtColor(frame_dibujado, cv2.COLOR_RGB2BGR) # Correccion color para st.image que espera RGB si no se especifica channels, pero frame_dibujado venia de RGB. Espera, frame_dibujado viene de frame_rgb que es RGB. st.image usa RGB por defecto.
                    # frame_dibujado es RGB. 
                    ventana_video.image(frame_dibujado)
                    
                cap.release()

    elif fuente_entrada == "📂 Subir Archivo":
        archivo = st.file_uploader("Cargar imagen", type=['jpg', 'png', 'jpeg'])
        if archivo:
            bytes_data = archivo.getvalue()
            img_opencv = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            # Detectar si el usuario sube un archivo lossless
            if archivo.name.lower().endswith((".bmp", ".png")):
                formato_origen = "PNG"
            else:
                formato_origen = "JPEG"

    elif fuente_entrada == "🔗 URL (Drive/Web)":
        url_raw = st.text_input("Pega el enlace de la imagen:")
        if url_raw:
            url_directa = convertir_link_drive(url_raw)
            if url_directa != url_raw:
                st.info(f"ℹ️ Enlace de Drive convertido a descarga directa.")
            
            # Descargar para poder procesarla con OpenCV localmente
            img_descargada = descargar_imagen_url(url_directa)
            if img_descargada is not None:
                # Convertir PIL (RGB) a OpenCV (BGR)
                img_opencv = cv2.cvtColor(img_descargada, cv2.COLOR_RGB2BGR)
                st.image(img_descargada, caption="Imagen Remota Verificada")
                # IMPORTANTE: Si es URL, guardamos la URL como texto para pasarla directa si se prefiere,
                # pero para aplicar el GATEKEEPER necesitamos procesarla localmente primero.
                # En este flujo híbrido, procesamos local para detectar cara, y luego enviamos el RECORTE.
                formato_origen = "URL" 
            else:
                st.error("No se pudo acceder a la imagen. Verifica el enlace.")

    # --- PROCESAMIENTO Y GATEKEEPER (DETECCIÓN DE ROSTRO) ---
    if img_opencv is not None:
        rostro_detectado = False
        rostro_para_ia = None
        
        # 1. Cargar Detector de Rostros
        try:
            # Usamos el clasificador predeterminado de OpenCV
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except:
            st.error("Error cargando Haar Cascade. Verifica tu instalación de OpenCV.")
            st.stop()

        # 2. Detectar Rostros
        gray = cv2.cvtColor(img_opencv, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        # 3. Dibujar Rectángulos (Feedback Visual)
        img_visual = img_opencv.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(img_visual, (x, y), (x+w, y+h), (0, 255, 0), 2)
        
        
        if fuente_entrada != "🔗 URL (Drive/Web)":
            st.image(img_visual, channels="BGR", caption="Detección Facial")
        if fuente_entrada != "🖐️ Cámara Inteligente (Gestos)":
            img_vis = img_opencv.copy()
            for (x, y, w, h) in faces:
                cv2.rectangle(img_vis, (x, y), (x+w, y+h), (0, 255, 0), 2)
            st.image(img_vis, channels="BGR", caption="Detección Facial")
        
        if len(faces) > 0:
            rostro_detectado = True
            # Seleccionar el rostro principal (el primero detectado)
            (x, y, w, h) = faces[0]
            
            # Aplicar margen para dar contexto a la IA (Mejora la precisión)
            margen = int(w * 0.15) 
            y1, y2 = max(0, y-margen), min(img_opencv.shape[0], y+h+margen)
            x1, x2 = max(0, x-margen), min(img_opencv.shape[1], x+w+margen)
            
            # Recortar el rostro para enviarlo a la IA
            rostro_para_ia = img_opencv[y1:y2, x1:x2]
        else:
            st.warning("⚠️  No se detectó ningún rostro claro. El análisis está bloqueado.")

        # --- BOTÓN DE ANÁLISIS (SOLO SI HAY ROSTRO) ---
        if rostro_detectado and rostro_para_ia is not None:
            if st.button("🔍 Analizar Rostro Detectado", type="primary"):
                if not api_key: 
                    st.warning("Falta API Key")
                else:
                    with st.spinner(f'Consultando IA ({modo_operacion})...'):
                        
                        # Preparar dato para IA (Siempre enviamos el recorte para mejor precisión)
                        if modo_operacion == " Gemini (Dev)":
                            img_rgb = cv2.cvtColor(rostro_para_ia, cv2.COLOR_BGR2RGB)
                            dato = PIL.Image.fromarray(img_rgb)
                            res = consultar_gemini(dato, api_key)
                        else:
                            # Azure: ai_services se encarga del formato. 
                            # Le pasamos el formato preferido detectado.
                            res = consultar_azure(rostro_para_ia, api_key, endpoint, deployment_name, formato_envio=formato_origen)

                        # Resultados
                        if res and "error" not in res:
                            nivel = res.get('nivel', 0)
                            st.session_state.ultimo_analisis = res
                            
                            # Guardar DB 
                            # Nota: Guardamos la imagen ORIGINAL completa para contexto histórico
                            is_success, buffer_img = cv2.imencode(".jpg", img_opencv)
                            if is_success:
                                guardar_registro(
                                    nivel=nivel,
                                    emocion=res.get('emocion_dominante', ''), 
                                    razon=res.get('razon', ''), 
                                    imagen_bytes=buffer_img.tobytes()
                                )
                                st.success("Guardado")

                            # Hardware
                            if nivel >= 4:
                                st.toast(f"🥤 TRISTEZA ({nivel}). DISPENSANDO...", icon="✅")
                                # Enviar comando (WiFi o Serial según configuración)
                                if target_hardware != "Sin Conexión": 
                                    if enviar_comando_esp32(target_hardware, es_wifi=usar_modo_wifi):
                                        st.success(f"Señal enviada a {target_hardware}")
                                else:
                                    st.warning("Hardware no conectado (Simulación Visual)")
                            else:
                                st.toast("😊 USUARIO FELIZ - NO DISPENSAR", icon="😴")
                           
                        
                        elif res: st.error(f"Error IA: {res.get('error')}")

with col2:
    st.write("### 2. Resultado Actual")
    if st.session_state.ultimo_analisis:
        res = st.session_state.ultimo_analisis
        nivel = res.get('nivel', 0)
        m1, m2 = st.columns(2)
        m1.metric("Nivel", f"{nivel}/10")
        m2.metric("Emoción", res.get('emocion_dominante', 'N/A'))
        st.progress(max(0, min(10, nivel)) / 10)
        st.info(f"**Diagnóstico:** {res.get('razon')}")
    else:
        st.info("Esperando análisis...")

st.divider()
st.subheader("🗄️ Historial Persistente")
df_historial = obtener_historial()
if not df_historial.empty:
    tab1, tab2, tab3 = st.tabs(["📋 Tabla", "📈 Gráfica", "💾 Descargas"])
    with tab1: st.dataframe(df_historial, use_container_width=True)
    with tab2: st.line_chart(df_historial.set_index("fecha")['nivel'])
    with tab3:
        opcion = st.selectbox("Selecciona ID:", df_historial['id'])
        if st.button("Ver y Descargar"):
            img_bytes = obtener_imagen_por_id(opcion)
            if img_bytes:
                st.image(img_bytes, caption=f"ID: {opcion}", width=300)
                st.download_button("⬇️ Descargar Foto", img_bytes, f"analisis_{opcion}.jpg", "image/jpeg")
else:
    st.info("Base de datos vacía.")