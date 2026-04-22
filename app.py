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
import requests

# ─── IMPORTACIÓN DE MÓDULOS PROPIOS ────────────────────────────────────────────
try:
    from ai_services import consultar_gemini, consultar_azure
    from db_services import init_db, guardar_registro, obtener_historial, obtener_imagen_por_id
except ImportError as e:
    st.error(f"Error crítico: Faltan archivos del proyecto ({e}).")
    st.stop()

try:
    from captura_gesto1 import DetectorGestos
except ImportError:
    DetectorGestos = None

# ─── CONFIGURACIÓN INICIAL ──────────────────────────────────────────────────────
st.set_page_config(
    page_title=" Detector de Tristeza",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

init_db()

# ─── INYECCIÓN DE CSS PERSONALIZADO ────────────────────────────────────────────
# Este bloque es el corazón del rediseño. Streamlit permite inyectar HTML/CSS
# arbitrario con st.markdown(..., unsafe_allow_html=True). Usamos variables CSS
# para mantener coherencia en toda la paleta de colores.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');

/* ── Variables de color ─────────────────────────── */
:root {
    --bg: #080c14;
    --surface: #0d1320;
    --surface2: #111927;
    --border: #1e2d42;
    --cyan: #00e5c8;
    --cyan-dim: rgba(0,229,200,0.10);
    --cyan-glow: rgba(0,229,200,0.3);
    --red: #ff4d6d;
    --red-dim: rgba(255,77,109,0.10);
    --yellow: #f5c542;
    --green: #4dff9a;
    --text: #c8d8e8;
    --text-muted: #5a7a9a;
    --text-bright: #e8f4ff;
}

/* ── Base de la app ─────────────────────────────── */
.stApp {
    background-color: var(--bg) !important;
    font-family: 'DM Sans', sans-serif;
    color: var(--text) !important;
}

/* Cuadrícula animada de fondo */
.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(0,229,200,0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,200,0.025) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
}

/* ── Barra lateral ──────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}

[data-testid="stSidebar"] * {
    color: var(--text) !important;
}

/* ── Botón primario (Analizar Emoción) ──────────── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #00e5c8, #00b4a0) !important;
    color: #080c14 !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 800 !important;
    font-size: 14px !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 14px 0 !important;
    width: 100% !important;
    position: relative !important;
    overflow: hidden !important;
    transition: all 0.3s !important;
    box-shadow: 0 4px 20px rgba(0,229,200,0.2) !important;
}

/* Efecto shimmer sobre el botón principal */
.stButton > button[kind="primary"]::after {
    content: '';
    position: absolute;
    top: -50%;
    left: -100%;
    width: 60%;
    height: 200%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
    transform: skewX(-15deg);
    animation: btnShimmer 3s ease-in-out infinite;
}

@keyframes btnShimmer {
    0% { left: -100%; }
    100% { left: 250%; }
}

.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 28px rgba(0,229,200,0.4) !important;
}

/* ── Botones secundarios ────────────────────────── */
.stButton > button:not([kind="primary"]) {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 12px !important;
    transition: all 0.2s !important;
}

.stButton > button:not([kind="primary"]):hover {
    border-color: var(--cyan) !important;
    color: var(--cyan) !important;
    background: var(--cyan-dim) !important;
}

/* ── Métricas ────────────────────────────────────── */
[data-testid="metric-container"] {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 16px !important;
}

[data-testid="metric-container"] label {
    font-family: 'DM Mono', monospace !important;
    font-size: 10px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    color: var(--text-muted) !important;
}

[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: 'Syne', sans-serif !important;
    font-size: 28px !important;
    font-weight: 800 !important;
    color: var(--cyan) !important;
}

/* ── Progress bar ────────────────────────────────── */
.stProgress > div > div {
    border-radius: 4px !important;
    background: var(--border) !important;
}

.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--green), var(--yellow), var(--red)) !important;
    border-radius: 4px !important;
    transition: width 1s ease-in-out !important;
}

/* ── Cajas de info/warning/error/success ─────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left-width: 4px !important;
    background: var(--surface2) !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* ── Tabs (Historial) ────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: var(--surface2) !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 4px !important;
}

.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-muted) !important;
    border-radius: 7px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 12px !important;
    transition: all 0.2s !important;
}

.stTabs [aria-selected="true"] {
    background: var(--cyan) !important;
    color: var(--bg) !important;
    font-weight: 600 !important;
}

/* ── Dataframe ───────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ── Selectbox & Text inputs ─────────────────────── */
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {
    background: var(--surface2) !important;
    border-color: var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 13px !important;
}

/* ── Cámara ──────────────────────────────────────── */
[data-testid="stCameraInput"] video,
[data-testid="stCameraInput"] img {
    border-radius: 10px !important;
    border: 2px solid var(--border) !important;
}

/* ── Radio buttons ───────────────────────────────── */
[data-testid="stRadio"] label {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 8px 14px !important;
    font-size: 12px !important;
    transition: all 0.2s !important;
}

[data-testid="stRadio"] label:has(input:checked) {
    background: var(--cyan-dim) !important;
    border-color: var(--cyan) !important;
    color: var(--cyan) !important;
}

/* ── Spinner ─────────────────────────────────────── */
.stSpinner > div {
    border-color: var(--cyan) transparent transparent transparent !important;
}

/* ── Divisor ─────────────────────────────────────── */
hr {
    border-color: var(--border) !important;
    margin: 24px 0 !important;
}

/* ── Scrollbar ───────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
</style>
""", unsafe_allow_html=True)


# ─── HELPER: SECCIÓN TÍTULO ─────────────────────────────────────────────────────
def render_section_title(numero: str, titulo: str):
    """Renderiza un título de sección con número en caja cyan y texto en mono."""
    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">
        <div style="width:22px; height:22px; background:#00e5c8; border-radius:5px;
                    display:flex; align-items:center; justify-content:center;
                    font-family:'Syne',sans-serif; font-weight:800; font-size:12px; color:#080c14;">
            {numero}
        </div>
        <span style="font-family:'DM Mono',monospace; font-size:11px; text-transform:uppercase;
                     letter-spacing:0.12em; color:#5a7a9a;">
            {titulo}
        </span>
    </div>
    """, unsafe_allow_html=True)


def render_resultado(res: dict):
    """
    Renderiza la tarjeta de resultado con un anillo cónico animado y colores
    que escalan con la intensidad de tristeza detectada.

    NOTA TÉCNICA: Se divide en tres st.markdown() independientes en lugar de
    uno solo. Esto evita que caracteres especiales en los valores dinámicos
    (backticks, comillas, HTML) que devuelve la IA rompan el bloque HTML
    completo y hagan que Streamlit lo muestre como texto plano/código.
    Adicionalmente, los valores dinámicos se escapan con html.escape() para
    neutralizar cualquier carácter conflictivo antes de insertarlos.
    """
    import html as html_lib

    nivel = res.get('nivel', 0)
    # Escapamos los valores que vienen de la IA para que no rompan el HTML
    emocion = html_lib.escape(str(res.get('emocion_dominante', 'N/A')))
    razon   = html_lib.escape(str(res.get('razon', '')))

    # Paleta de colores escalonada por nivel de tristeza
    if nivel >= 7:
        color, emoji, label = "#ff4d6d", "😢", "Alta intensidad"
    elif nivel >= 4:
        color, emoji, label = "#f5c542", "😟", "Intensidad media"
    else:
        color, emoji, label = "#4dff9a", "🙂", "Baja intensidad"

    porcentaje = int((nivel / 10) * 100)

    # ── Bloque 1: Anillo cónico + animación fadeInScale ──────────────────────
    # Se aísla aquí para que los valores puramente numéricos (nivel, porcentaje,
    # color) no puedan verse afectados por el contenido textual de la IA.
    st.markdown(f"""
    <style>
    @keyframes fadeInScale {{
        from {{ opacity:0; transform:scale(0.75); }}
        to   {{ opacity:1; transform:scale(1); }}
    }}
    </style>
    <div style="text-align:center; padding: 16px 0 8px;">
        <div style="
            width:110px; height:110px;
            border-radius:50%;
            background: conic-gradient({color} 0% {porcentaje}%, #1e2d42 {porcentaje}%);
            display:flex; flex-direction:column;
            align-items:center; justify-content:center;
            margin: 0 auto 14px;
            position: relative;
            animation: fadeInScale 0.6s ease-out;
        ">
            <div style="
                position:absolute; inset:8px; border-radius:50%;
                background:#111927;
            "></div>
            <span style="font-family:'Syne',sans-serif; font-weight:800; font-size:32px;
                         color:{color}; position:relative; z-index:1;
                         text-shadow: 0 0 20px {color}80; line-height:1;">
                {nivel}
            </span>
            <span style="font-family:'DM Mono',monospace; font-size:11px;
                         color:#5a7a9a; position:relative; z-index:1;">/ 10</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Bloque 2: Badge de emoción ────────────────────────────────────────────
    # Separado del anillo para que si `emocion` contiene caracteres extraños
    # (después del escape) solo afecte este bloque y no el anillo ni el diagnóstico.
    st.markdown(f"""
    <div style="text-align:center; margin-bottom:12px;">
        <div style="
            display:inline-flex; align-items:center; gap:6px;
            padding:6px 16px; border-radius:20px;
            background:{color}18;
            border:1px solid {color}50;
            color:{color};
            font-family:'DM Mono',monospace; font-size:12px; font-weight:500;
        ">
            {emoji}&nbsp;{emocion}&nbsp;·&nbsp;{label}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Bloque 3: Caja de diagnóstico ─────────────────────────────────────────
    # La razón es el texto más largo y variable que devuelve la IA, por lo que
    # se aísla completamente. El html.escape() previene inyección de HTML.
    st.markdown(f"""
    <div style="
        background:#080c14; border:1px solid #1e2d42;
        border-left:3px solid {color};
        border-radius:8px; padding:12px 14px;
        font-size:12px; color:#c8d8e8; line-height:1.7;
        margin-bottom:8px;
    ">
        <strong style="color:{color}; font-family:'DM Mono',monospace;
                       font-size:10px; text-transform:uppercase; letter-spacing:0.1em;">
            Diagnóstico IA
        </strong><br><br>
        {razon}
    </div>
    """, unsafe_allow_html=True)

def aplicar_marco_polaroid(img_bgr, face_rect, res):
    """
    Añade marco estilo Polaroid a la imagen antes de guardarla en la BD.

    Resultado visual:
    - Esquinas en L de color alrededor del rostro detectado
    - Franja oscura añadida DEBAJO del canvas (no sobre la imagen)
      con: emoji grande | nivel X/10 | emoción | fecha y hora
    - Color escala con el nivel: verde (0-3), amarillo (4-6), rojo (7-10)

    Usa PIL para todo (soporte de emoji y fuentes del sistema).
    Recibe y devuelve formato BGR de OpenCV.
    """
    from PIL import Image, ImageDraw, ImageFont
    from datetime import datetime

    nivel   = res.get('nivel', 0)
    emocion = res.get('emocion_dominante', 'N/A').upper()
    ahora   = datetime.now()
    fecha_str = ahora.strftime("%d/%m/%Y")
    hora_str  = ahora.strftime("%H:%M:%S")

    # ── Paleta según nivel ────────────────────────────────────────────────────
    if nivel >= 7:
        color_rgb  = (255,  77, 109)   # rojo
        emoji_text = "😢"
    elif nivel >= 4:
        color_rgb  = (245, 197,  66)   # amarillo
        emoji_text = "😟"
    else:
        color_rgb  = ( 77, 255, 154)   # verde
        emoji_text = "🙂"

    # ── Convertir BGR → PIL RGB ───────────────────────────────────────────────
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    W, H    = pil_img.size

    draw = ImageDraw.Draw(pil_img)

    # ── Esquinas en L alrededor del rostro ────────────────────────────────────
    if face_rect is not None:
        fx, fy, fw, fh = face_rect
        margen = int(fw * 0.15)                  # mismo margen que usa app.py
        x1 = max(0, fx - margen)
        y1 = max(0, fy - margen)
        x2 = min(W, fx + fw + margen)
        y2 = min(H, fy + fh + margen)

        L = max(15, min(int(min(fw, fh) * 0.18), int(W * 0.06)))
        T = max(3,  min(int(min(fw, fh) * 0.025), 8))    # grosor del trazo
        c = color_rgb

        # Superior izquierda
        draw.rectangle([x1,     y1,     x1 + L, y1 + T], fill=c)
        draw.rectangle([x1,     y1,     x1 + T, y1 + L], fill=c)
        # Superior derecha
        draw.rectangle([x2 - L, y1,     x2,     y1 + T], fill=c)
        draw.rectangle([x2 - T, y1,     x2,     y1 + L], fill=c)
        # Inferior izquierda
        draw.rectangle([x1,     y2 - T, x1 + L, y2    ], fill=c)
        draw.rectangle([x1,     y2 - L, x1 + T, y2    ], fill=c)
        # Inferior derecha
        draw.rectangle([x2 - L, y2 - T, x2,     y2    ], fill=c)
        draw.rectangle([x2 - T, y2 - L, x2,     y2    ], fill=c)

    # ── Franja Polaroid inferior ──────────────────────────────────────────────
    strip_h = max(120, int(H * 0.20))   

    # Canvas extendido con fondo oscuro (coherente con el tema de la app)
    new_img = Image.new("RGB", (W, H + strip_h), (8, 12, 20))
    new_img.paste(pil_img, (0, 0))
    sd = ImageDraw.Draw(new_img)

    # Fondo de la franja
    sd.rectangle([0, H, W, H + strip_h], fill=(13, 19, 32))

    # Línea divisoria del color del nivel (3px)
    sd.rectangle([0, H, W, H + 3], fill=color_rgb)

    # ── Cargar fuentes del sistema con fallback ───────────────────────────────
    def load_font(paths, size):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    #sz_big   = max(32, strip_h // 3)
    #sz_small = max(13, strip_h // 7)
    sz_big   = max(28, min(int(W * 0.08), int(strip_h * 0.45)))
    sz_small = max(14, min(int(W * 0.03), int(strip_h * 0.22)))
    font_emoji   = load_font([
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/Segoe UI Emoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    ], sz_big)

    font_level   = load_font([
        "C:/Windows/Fonts/arialbold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ], sz_big)

    font_small   = load_font([
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ], sz_small)

    # ── Layout de la franja en 3 zonas ────────────────────────────────────────
    #   [ EMOJI ]  [ NIVEL ]  [ EMOCIÓN / FECHA ]
    cy  = H + strip_h // 2   # centro vertical de la franja
    pad = 16

    # Zona izquierda — emoji grande
    sd.text(
        (pad + sz_big // 2, cy),
        emoji_text,
        font=font_emoji, anchor="mm", embedded_color=True
    )

    # Zona central — nivel en color
    sd.text(
        (W // 2, cy),
        f"{nivel} / 10",
        font=font_level, fill=color_rgb, anchor="mm"
    )

    # Zona derecha — emoción arriba, fecha+hora abajo
    right_x = W - pad
    sd.text(
        (right_x, cy - sz_small // 2 - 3),
        emocion,
        font=font_small, fill=(200, 216, 232), anchor="rm"
    )
    sd.text(
        (right_x, cy + sz_small // 2 + 3),
        f"{fecha_str}  {hora_str}",
        font=font_small, fill=(90, 122, 154), anchor="rm"
    )

    # ── Devolver en BGR para OpenCV ───────────────────────────────────────────
    return cv2.cvtColor(np.array(new_img), cv2.COLOR_RGB2BGR)
def render_alerta_dispensador(nivel: int, destino: str):
    """
    Muestra una alerta animada pulsante cuando el nivel de tristeza
    es suficiente para activar el dispensador de bebidas.
    """
    if nivel >= 4:
        color = "#ff4d6d" if nivel >= 7 else "#f5c542"
        icono = "🥤" if nivel >= 7 else "🧋"
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {color}10, {color}05);
            border: 1px solid {color}60;
            border-radius:10px; padding:14px 18px;
            display:flex; align-items:center; gap:12px;
            animation: alertPulse 2s ease-in-out infinite;
            margin-top: 12px;
        ">
            <span style="font-size:28px; animation: bounce 1s ease infinite;">{icono}</span>
            <div>
                <div style="font-size:13px; color:{color}; font-weight:500;">
                    Nivel {nivel} — Dispensando bebida reconfortante
                </div>
                <div style="font-size:11px; color:{color}90;
                            font-family:'DM Mono',monospace; margin-top:2px;">
                    Señal enviada → {destino}
                </div>
            </div>
        </div>
        <style>
        @keyframes alertPulse {{
            0%, 100% {{ border-color: {color}60; }}
            50% {{ border-color: {color}cc; box-shadow: 0 0 20px {color}20; }}
        }}
        @keyframes bounce {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-5px); }}
        }}
        </style>
        """, unsafe_allow_html=True)


# ─── HEADER PRINCIPAL ───────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom: 28px;">
    <h1 style="
        font-family:'Syne',sans-serif; font-weight:800; font-size:34px;
        color:#e8f4ff; line-height:1.1; letter-spacing:-0.02em; margin:0;
    ">
        Detector de <span style="color:#00e5c8;
        text-shadow: 0 0 24px rgba(0,229,200,0.5);">Tristeza</span> 
    </h1>
    <p style="font-family:'DM Mono',monospace; font-size:12px;
              color:#5a7a9a; margin-top:6px; letter-spacing:0.06em;">
        // Sistema de Mitigación Emocional · Visión Computacional + Hardware Dispensador
    </p>
</div>
""", unsafe_allow_html=True)


# ─── INICIALIZACIÓN DE ESTADO ────────────────────────────────────────────────────
for key, default in [
    ('ultimo_analisis', None),
    ('conteo_activo', False),
    ('inicio_conteo', 0),
    ('foto_gesto_capturada', None),
     ('ultimo_dispensado', None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

def render_reflexion(nivel: int):
    """
    Muestra una imagen de reflexión/chiste y reproduce una canción
    automáticamente según el rango de nivel de tristeza.
    Audio embebido en base64 para autoplay sin controles visibles.
    """
    import base64
    import os

    # ── Mapeo de rangos a archivos ────────────────────────────────────────────
    if nivel <= 2:
        rango     = "0_2"
        titulo    = "😄 ¡Todo bien por aquí!"
        subtitulo = "Sigue así, estás genial"
        color     = "#4dff9a"
    elif nivel <= 4:
        rango     = "3_4"
        titulo    = "🙂 Un poco de ánimo..."
        subtitulo = "Algo de música para subir los ánimos"
        color     = "#00e5c8"
    elif nivel <= 6:
        rango     = "5_6"
        titulo    = "😟 Detectamos algo de tristeza"
        subtitulo = "Una reflexión para ti"
        color     = "#f5c542"
    elif nivel <= 8:
        rango     = "7_8"
        titulo    = "😢 Parece que no estás bien tú puedes guerrero"
        subtitulo = "Aquí hay algo que puede ayudarte"
        color     = "#ff8c42"
    else:
        rango     = "9_10"
        titulo    = "😭 Oye, todo va a estar bien"
        subtitulo = "Tómate un momento, mereces un descanso"
        color     = "#ff4d6d"

    img_path   = f"assets/reflexion/rango_{rango}.gif"
    audio_path = f"assets/reflexion/rango_{rango}.mp3"

    # ── Título de la sección ──────────────────────────────────────────────────
    st.markdown(f"""
    <div style="
        margin-top:20px;
        border-top:1px solid #1e2d42;
        padding-top:16px;
    ">
        <div style="font-family:'DM Mono',monospace; font-size:10px;
                    text-transform:uppercase; letter-spacing:0.12em;
                    color:{color}; margin-bottom:4px;">
            {titulo}
        </div>
        <div style="font-size:11px; color:#5a7a9a;">
            {subtitulo}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Imagen de reflexión ───────────────────────────────────────────────────
    if os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    else:
        st.markdown(f"""
        <div style="background:#0d1320; border:2px dashed #1e2d42;
                    border-radius:8px; padding:20px; text-align:center;
                    color:#5a7a9a; font-family:'DM Mono',monospace; font-size:11px;">
            📂 Imagen no encontrada:<br>{img_path}
        </div>
        """, unsafe_allow_html=True)

    # ── Audio automático sin controles visibles ───────────────────────────────
    # Se embebe como base64 para que el navegador lo reproduzca directamente.
    # Funciona porque el usuario acaba de hacer clic en "Analizar" (interacción
    # requerida por los navegadores modernos para permitir autoplay).
    if os.path.exists(audio_path):
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        # Detectar formato por extensión
        ext = audio_path.rsplit(".", 1)[-1].lower()
        mime = "audio/wav" if ext == "wav" else "audio/mpeg"

        st.markdown(f"""
        <audio autoplay style="display:none;">
            <source src="data:{mime};base64,{audio_b64}" type="{mime}">
        </audio>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="color:#5a7a9a; font-family:'DM Mono',monospace;
                    font-size:10px; margin-top:6px;">
            🎵 Audio no encontrado: {audio_path}
        </div>
        """, unsafe_allow_html=True)
# ─── UTILIDADES ─────────────────────────────────────────────────────────────────
def convertir_link_drive(url):
    """Convierte un enlace de vista de Google Drive en URL de descarga directa."""
    if "drive.google.com" in url and "/view" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except Exception:
            return url
    return url


def descargar_imagen_url(url):
    """Descarga una imagen desde una URL y la devuelve como array NumPy."""
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return np.array(PIL.Image.open(io.BytesIO(resp.content)))
    except Exception:
        return None
    return None


# ─── GESTIÓN HARDWARE ───────────────────────────────────────────────────────────
def enviar_comando_esp32(destino, nivel=0, es_wifi=False):
    if not destino or destino == "Sin Conexión":
        return False, "Sin conexión configurada"

    if es_wifi:
        try:
            url_con_nivel = f"{destino}?nivel={nivel}"
            respuesta = requests.get(url_con_nivel, timeout=23)
            # El body ya contiene el mensaje del ESP32:
            # "OK: Proceso finalizado." / "ERROR: Coloque el vaso primero." / etc.
            mensaje = respuesta.text.strip()
            if respuesta.status_code == 200:
                exito = not mensaje.startswith("ERROR:")   # ← True solo si el ESP32 dice OK
                return exito, mensaje
            else:
                return False, f"ESP32 respondió con código {respuesta.status_code}: {mensaje}"
        except requests.exceptions.Timeout:
            return False, "ESP32 no respondió (Timeout). Verifica la IP y el WiFi."
        except requests.exceptions.ConnectionError:
            return False, "No se pudo conectar con el ESP32. Verifica la IP y el WiFi."
        except Exception as e:
            return False, f"Error WiFi inesperado: {e}"

    else:
        try:
            es_simulacion = "socket://" in destino
            if es_simulacion:
                with serial.serial_for_url(destino, baudrate=115200, timeout=2) as ser:
                    ser.write(f'bebida?nivel={nivel}\n'.encode())
                return True, "Comando enviado (simulación)"

            ser = serial.Serial(destino, 115200, timeout=3)

            # Esperar boot completo
            deadline_boot = time.time() + 10
            while time.time() < deadline_boot:
                linea = ser.readline().decode(errors='replace')
                if "Sistema listo" in linea:
                    break

            ser.reset_input_buffer()
            time.sleep(0.1)
            ser.write(f'bebida?nivel={nivel}\n'.encode())
            ser.flush()

            # Leer respuesta real de uart_task — puede tardar hasta TIEMPO_NIVEL_MAX
            mensaje = "Sin respuesta de uart_task"
            deadline_resp = time.time() + 15
            while time.time() < deadline_resp:
                linea = ser.readline().decode(errors='replace').strip()
                if linea.startswith("OK:") or linea.startswith("ERROR:"):
                    mensaje = linea
                    break

            ser.close()
            exito = mensaje.startswith("OK:")
            return exito, mensaje

        except serial.SerialException as e:
            if "Access is denied" in str(e) or "PermissionError" in str(e):
                return False, "Puerto ocupado: cierra el Monitor Serial en VS Code."
            return False, f"Error Serial: {e}"
        except Exception as e:
            return False, f"Error General Hardware: {e}"
# ─── BARRA LATERAL ──────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo animado con glow en la barra lateral
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px;
                padding-bottom:20px; border-bottom:1px solid #1e2d42; margin-bottom:4px;">
        <div style="width:36px; height:36px; background:rgba(0,229,200,0.1);
                    border:1px solid #00e5c8; border-radius:8px;
                    display:flex; align-items:center; justify-content:center;
                    font-size:18px; animation: glow 2s ease-in-out infinite;">
        </div>
        <div>
            <div style="font-family:'Syne',sans-serif; font-weight:800; font-size:14px;
                        color:#e8f4ff; line-height:1.2;">Tristómetro</div>
            <div style="font-family:'DM Mono',monospace; font-size:10px; color:#00e5c8;
                        letter-spacing:0.08em; text-transform:uppercase;">Sistema Activo</div>
        </div>
    </div>
    <style>
    @keyframes glow {
        0%, 100% { box-shadow: 0 0 8px rgba(0,229,200,0.3); }
        50% { box-shadow: 0 0 20px rgba(0,229,200,0.5); }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<p style="font-family:\'DM Mono\',monospace; font-size:10px; '
                'text-transform:uppercase; letter-spacing:0.12em; color:#5a7a9a; '
                'margin-top:20px;">🔌 Hardware Dispensador</p>', unsafe_allow_html=True)

    tipo_conexion = st.radio("Método:", ["🔌 Serial / Simulación", "📡 WiFi (HTTP)"],
                             label_visibility="collapsed")

    target_hardware = "Sin Conexión"
    usar_modo_wifi = False

    if tipo_conexion == "📡 WiFi (HTTP)":
        usar_modo_wifi = True
        target_hardware = st.text_input(
            "URL del ESP32:", value="http://192.168.137.100/bebida",
            help="Debe incluir http:// y la ruta configurada en el ESP32"
        )
    else:
        try:
            ports = serial.tools.list_ports.comports()
            opciones_puertos = [p.device for p in ports]
        except Exception:
            opciones_puertos = []

        opciones_puertos.insert(0, "socket://localhost:4000")
        opciones_puertos.insert(0, "Sin Conexión")

        selected_port = st.selectbox("Puerto:", options=opciones_puertos, index=1)
        if st.button("🔄 Refrescar Puertos"):
            st.rerun()
        target_hardware = selected_port

    st.divider()

    st.markdown('<p style="font-family:\'DM Mono\',monospace; font-size:10px; '
                'text-transform:uppercase; letter-spacing:0.12em; color:#5a7a9a;">🤖 Modelo IA</p>',
                unsafe_allow_html=True)

    modo_operacion = st.radio("Cerebro:", ["🤖 Gemini (Dev)", "☁️ Azure (Prod)"],
                              label_visibility="collapsed")

    if modo_operacion == "🤖 Gemini (Dev)":
        api_key = st.text_input("Gemini API Key", type="password", value="")
        endpoint = None
        deployment_name = None
    else:
        api_key = st.text_input("Azure API Key", type="password", value="")
        endpoint = st.text_input("Azure Endpoint", value="")
        deployment_name = st.text_input("Nombre Despliegue", value="gpt-5-chat")

    # Indicadores de estado tipo LED en la parte inferior del sidebar
    api_color = "#4dff9a" if api_key else "#5a7a9a"
    hw_color = "#4dff9a" if target_hardware != "Sin Conexión" else "#5a7a9a"
    api_anim = "animation:blink 1.2s infinite;" if api_key else ""
    hw_anim = "animation:blink 1.2s infinite;" if target_hardware != "Sin Conexión" else ""

    st.markdown(f"""
    <div style="display:flex; flex-direction:column; gap:6px; margin-top:16px;">
        <div style="display:flex; align-items:center; gap:8px; font-family:'DM Mono',monospace;
                    font-size:11px; color:{api_color};">
            <span style="width:7px; height:7px; border-radius:50%;
                         background:{api_color}; {api_anim}"></span>
            API Key {"configurada ✓" if api_key else "no configurada"}
        </div>
        <div style="display:flex; align-items:center; gap:8px; font-family:'DM Mono',monospace;
                    font-size:11px; color:{hw_color};">
            <span style="width:7px; height:7px; border-radius:50%;
                         background:{hw_color}; {hw_anim}"></span>
            ESP32 {"conectado ✓" if target_hardware != "Sin Conexión" else "sin conexión"}
        </div>
    </div>
    <style>
    @keyframes blink {{
        0%, 100% {{ opacity:1; }} 50% {{ opacity:0.2; }}
    }}
    </style>
    """, unsafe_allow_html=True)


# ─── CAPTURA Y ANÁLISIS ─────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    render_section_title("1", "Fuente de Imagen")

    fuente_entrada = st.radio(
        "Selecciona el origen:",
        ["📸 Cámara Web", "🖐️ Cámara Inteligente (Gestos)", "📂 Subir Archivo", "🔗 URL (Drive/Web)"],
        horizontal=True,
        label_visibility="collapsed"
    )

    img_opencv = None
    formato_origen = "JPEG"

    # ── Cámara Web ──────────────────────────────────────────────────────────────
    if fuente_entrada == "📸 Cámara Web":
        img_cam = st.camera_input("Capturar", label_visibility="collapsed")
        if img_cam:
            bytes_data = img_cam.getvalue()
            img_opencv = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            formato_origen = "PNG"

    # ── Cámara Inteligente (Gestos) ─────────────────────────────────────────────
    elif fuente_entrada == "🖐️ Cámara Inteligente (Gestos)":
        if DetectorGestos is None:
            st.error("⚠️ Falta 'captura_gesto1.py' o 'hand_landmarker.task'.")
        else:
            iniciar_stream = st.checkbox("🔴 Activar Cámara", value=False)
            ventana_video = st.image([])
            texto_estado = st.empty()

            if st.session_state.foto_gesto_capturada is not None and not iniciar_stream:
                img_opencv = st.session_state.foto_gesto_capturada
                st.image(img_opencv, caption="📸 Foto capturada por gesto", channels="BGR")
                formato_origen = "PNG"

            elif iniciar_stream:
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
                    if not ret:
                        break

                    frame = cv2.flip(frame, 1)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame_dibujado, gesto = st.session_state.detector_gestos.detectar_estado_mano(frame_rgb.copy())

                    if gesto == "PALMA" and not st.session_state.conteo_activo:
                        st.session_state.conteo_activo = True
                        st.session_state.inicio_conteo = time.time()
                    elif gesto == "PUNO" and st.session_state.conteo_activo:
                        st.session_state.conteo_activo = False
                        texto_estado.warning("⏹️ Cancelado")

                    if st.session_state.conteo_activo:
                        restante = 5 - int(time.time() - st.session_state.inicio_conteo)
                        if restante > 0:
                            cv2.putText(frame_dibujado, str(restante), (50, 150),
                                        cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 229, 200), 8)
                            texto_estado.info(f"📸 Tomando foto en {restante}...")
                        else:
                            texto_estado.success("📸 ¡Captura realizada!")
                            st.session_state.foto_gesto_capturada = frame
                            st.session_state.conteo_activo = False
                            img_opencv = frame
                            formato_origen = "PNG"
                            cap.release()
                            st.rerun()
                            break

                    ventana_video.image(frame_dibujado)

                cap.release()

    # ── Subir Archivo ────────────────────────────────────────────────────────────
    elif fuente_entrada == "📂 Subir Archivo":
        archivo = st.file_uploader("Cargar imagen", type=['jpg', 'png', 'jpeg'],
                                   label_visibility="collapsed")
        if archivo:
            bytes_data = archivo.getvalue()
            img_opencv = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            formato_origen = "PNG" if archivo.name.lower().endswith((".bmp", ".png")) else "JPEG"

    # ── URL (Drive / Web) ────────────────────────────────────────────────────────
    elif fuente_entrada == "🔗 URL (Drive/Web)":
        url_raw = st.text_input("Pega el enlace:",
                                placeholder="https://drive.google.com/... o cualquier URL directa")
        if url_raw:
            url_directa = convertir_link_drive(url_raw)
            if url_directa != url_raw:
                st.info("ℹ️ Enlace de Drive convertido a URL de descarga directa.")
            img_descargada = descargar_imagen_url(url_directa)
            if img_descargada is not None:
                img_opencv = cv2.cvtColor(img_descargada, cv2.COLOR_RGB2BGR)
                st.image(img_descargada, caption="Imagen Remota Verificada", use_container_width=True)
                formato_origen = "URL"
            else:
                st.error("No se pudo acceder a la imagen. Verifica el enlace.")

    # ─── GATEKEEPER: Detección de Rostro ────────────────────────────────────────
    # Se activa solo cuando hay imagen disponible. Si no hay rostro visible,
    # el botón de analizar no aparece (evitamos llamadas innecesarias a la API).
    if img_opencv is not None:
        rostro_detectado = False
        rostro_para_ia = None

        try:
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
        except Exception:
            st.error("Error cargando Haar Cascade. Verifica tu instalación de OpenCV.")
            st.stop()

        gray = cv2.cvtColor(img_opencv, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        # Bounding boxes en cyan (#00e5c8) para coherencia con el tema visual
        img_visual = img_opencv.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(img_visual, (x, y), (x + w, y + h), (0, 229, 200), 2)
            cv2.putText(img_visual, "Rostro", (x, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 229, 200), 1)

        # BUG CORREGIDO: imagen de detección se mostraba DOS VECES en el original
        # (líneas 340-345). Ahora solo se muestra una vez con la lógica correcta.
        if fuente_entrada != "🔗 URL (Drive/Web)":
            st.image(img_visual, channels="BGR", caption="Detección Facial",
                     use_container_width=True)

        if len(faces) > 0:
            rostro_detectado = True
            (x, y, w, h) = faces[0]
            margen = int(w * 0.15)
            y1 = max(0, y - margen)
            y2 = min(img_opencv.shape[0], y + h + margen)
            x1 = max(0, x - margen)
            x2 = min(img_opencv.shape[1], x + w + margen)
            rostro_para_ia = img_opencv[y1:y2, x1:x2]
        else:
            st.warning("⚠️ No se detectó ningún rostro claro. El análisis está bloqueado.")

        if rostro_detectado and rostro_para_ia is not None:
            if st.button("⚡ Analizar Emoción Detectada", type="primary", use_container_width=True):
                if not api_key:
                    st.warning("⚠️ Falta configurar la API Key en la barra lateral.")
                else:
                    with st.spinner("Consultando IA... analizando expresión facial..."):
                        if "Gemini" in modo_operacion:
                            img_rgb = cv2.cvtColor(rostro_para_ia, cv2.COLOR_BGR2RGB)
                            dato = PIL.Image.fromarray(img_rgb)
                            res = consultar_gemini(dato, api_key)
                        else:
                            res = consultar_azure(rostro_para_ia, api_key, endpoint,
                                                  deployment_name, formato_envio=formato_origen)

                    if res and "error" not in res:
                        nivel = res.get('nivel', 0)
                        st.session_state.ultimo_analisis = res
                        face_rect = faces[0] if len(faces) > 0 else None
                        img_para_guardar = aplicar_marco_polaroid(img_opencv, face_rect, res)
                        st.image(img_para_guardar, channels="BGR", caption="DEBUG — imagen que se guardará")

                        is_success, buffer_img = cv2.imencode(".jpg", img_para_guardar)
                        if is_success:
                            guardar_registro(
                                nivel=nivel,
                                emocion=res.get('emocion_dominante', ''),
                                razon=res.get('razon', ''),
                                imagen_bytes=buffer_img.tobytes()
                            )
                            st.toast("✅ Análisis guardado en base de datos", icon="💾")
                        if nivel >= 0:
                                if target_hardware != "Sin Conexión":
                                    with st.spinner("Comunicando con dispensador..."):
                                        exito, mensaje_esp32 = enviar_comando_esp32(
                                            target_hardware, nivel=nivel, es_wifi=usar_modo_wifi
                                        )
                                    # Guardar en session_state para mostrarlo persistentemente
                                    st.session_state.ultimo_dispensado = {
                                        "exito":   exito,
                                        "mensaje": mensaje_esp32,
                                        "nivel":   nivel,
                                    }
                                else:
                                    st.session_state.ultimo_dispensado = {
                                        "exito":   None,   # None = sin hardware
                                        "mensaje": "Hardware no conectado.",
                                        "nivel":   nivel,
                                    }
                        if nivel <= 4:
                                st.toast("😊 Usuario feliz ", icon="😴")
                                
                    elif res:
                        st.error(f"Error IA: {res.get('error')}")
                   



# ─── COLUMNA 2: RESULTADO ───────────────────────────────────────────────────────
with col2:
    render_section_title("2", "Resultado del Análisis")

    if st.session_state.ultimo_analisis:
        res = st.session_state.ultimo_analisis
        nivel = res.get('nivel', 0)

        render_resultado(res)

        m1, m2 = st.columns(2)
        m1.metric("Nivel de Tristeza", f"{nivel} / 10")
        m2.metric("Emoción", res.get('emocion_dominante', 'N/A'))

        # Barra de progreso con transición CSS de 1 segundo
        st.progress(max(0, min(10, nivel)) / 10)

        render_alerta_dispensador(nivel, target_hardware)
        render_reflexion(nivel)
        # ── Resultado persistente del dispensador ────────────────────────────
        disp = st.session_state.get("ultimo_dispensado")
        if disp:
            if disp["exito"] is True:
                st.markdown(f"""
                <div style="
                    background:#0d1320; border:1px solid #4dff9a60;
                    border-left:3px solid #4dff9a;
                    border-radius:8px; padding:12px 16px; margin-top:10px;
                ">
                    <div style="color:#4dff9a; font-family:'DM Mono',monospace;
                                font-size:10px; text-transform:uppercase;
                                letter-spacing:0.1em; margin-bottom:4px;">
                        ✅ Dispensado — Nivel {disp['nivel']}
                    </div>
                    <div style="color:#c8d8e8; font-size:12px;">
                        {disp['mensaje']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            elif disp["exito"] is False:
                st.markdown(f"""
                <div style="
                    background:#0d1320; border:1px solid #ff4d6d60;
                    border-left:3px solid #ff4d6d;
                    border-radius:8px; padding:12px 16px; margin-top:10px;
                ">
                    <div style="color:#ff4d6d; font-family:'DM Mono',monospace;
                                font-size:10px; text-transform:uppercase;
                                letter-spacing:0.1em; margin-bottom:4px;">
                        ⚠️ Error en Dispensador
                    </div>
                    <div style="color:#c8d8e8; font-size:12px;">
                        {disp['mensaje']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            else:
                # exito is None → sin hardware conectado
                st.markdown(f"""
                <div style="
                    background:#0d1320; border:1px solid #f5c54260;
                    border-left:3px solid #f5c542;
                    border-radius:8px; padding:12px 16px; margin-top:10px;
                ">
                    <div style="color:#f5c542; font-family:'DM Mono',monospace;
                                font-size:10px; text-transform:uppercase;
                                letter-spacing:0.1em; margin-bottom:4px;">
                        ⚠️ Sin Hardware
                    </div>
                    <div style="color:#c8d8e8; font-size:12px;">
                        {disp['mensaje']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        # Placeholder vacío con diseño coherente al tema
        st.markdown("""
        <div style="
            background: #0d1320; border: 2px dashed #1e2d42;
            border-radius:12px; padding:50px 20px;
            text-align:center; color:#5a7a9a;
        ">
            <div style="font-size:40px; margin-bottom:10px; opacity:0.4;">🧠</div>
            <div style="font-family:'DM Mono',monospace; font-size:12px;
                        text-transform:uppercase; letter-spacing:0.1em;">
                Esperando análisis...
            </div>
            <div style="font-size:11px; margin-top:6px; color:#3a5a7a;">
                Captura o sube una imagen con un rostro visible
            </div>
        </div>
        """, unsafe_allow_html=True)


# ─── HISTORIAL ──────────────────────────────────────────────────────────────────
st.divider()
render_section_title("3", "Historial Persistente")

df_historial = obtener_historial()

if not df_historial.empty:
    tab1, tab2, tab3 = st.tabs(["📈 Gráfica", "📋 Tabla", "💾 Descargas"])

    with tab1:
        import plotly.graph_objects as go

        df_chart = df_historial.sort_values("fecha").reset_index(drop=True)

        fig = go.Figure()

        # ── Bandas de fondo por zona emocional (van primero para quedar detrás) ──
        for y0, y1, color, etiqueta in [
            (0,  3,  "rgba(77,255,154,0.07)",  "Bajo 0–3"),
            (3,  6,  "rgba(245,197,66,0.07)",  "Medio 3–6"),
            (6, 10,  "rgba(255,77,109,0.07)",  "Alto 6–10"),
        ]:
            fig.add_hrect(
                y0=y0, y1=y1,
                fillcolor=color,
                line_width=0,
                annotation_text=etiqueta,
                annotation_position="left",
                annotation_font=dict(color="#5a7a9a", size=9),
            )

        # ── Área rellena bajo la línea ────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=df_chart.index,
            y=df_chart["nivel"],
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(0,229,200,0.06)",
            line=dict(color="#00e5c8", width=2),
            customdata=list(zip(df_chart["emocion"], df_chart["nivel"], df_chart["fecha"])),
            hovertemplate=(
                "<b>%{customdata[2]}</b><br>"
                "Nivel: %{customdata[1]} / 10<br>"
                "Emoción: %{customdata[0]}<br>"
                "<extra></extra>"
            ),
        ))

        # ── Puntos individuales coloreados por nivel ──────────────────────────
        def color_por_nivel(n):
            if n <= 3:   return "#4dff9a"
            elif n <= 6: return "#f5c542"
            else:        return "#ff4d6d"

        fig.add_trace(go.Scatter(
            x=df_chart.index,
            y=df_chart["nivel"],
            mode="markers",
            marker=dict(
                color=[color_por_nivel(n) for n in df_chart["nivel"]],
                size=6,
                line=dict(width=0),
            ),
           customdata=list(zip(df_chart["emocion"], df_chart["nivel"], df_chart["fecha"])),
           hovertemplate=(
                "<b>%{customdata[2]}</b><br>"
                "Nivel: %{customdata[1]} / 10<br>"
                "Emoción: %{customdata[0]}<br>"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ── Línea de promedio ─────────────────────────────────────────────────
        promedio = df_chart["nivel"].mean()
        fig.add_hline(
            y=promedio,
            line_dash="dash",
            line_color="rgba(0,229,200,0.4)",
            line_width=1,
            annotation_text=f"Promedio: {promedio:.1f}",
            annotation_position="top right",
            annotation_font=dict(color="#00e5c8", size=11),
        )

        # ── Estilo coherente con el tema de la app ────────────────────────────
        fig.update_layout(
            plot_bgcolor  = "#080c14",
            paper_bgcolor = "#0d1320",
            font          = dict(family="DM Mono, monospace", color="#5a7a9a", size=11),
            xaxis=dict(
                showgrid   = False,
                linecolor  = "#1e2d42",
                tickmode   = "array",
                # Mostrar solo ~10 ticks distribuidos para no saturar el eje
                tickvals   = list(df_chart.index[::max(1, len(df_chart)//10)]),
                ticktext   = [
                    df_chart["fecha"].iloc[i][:10]   # solo la fecha sin hora
                    for i in range(0, len(df_chart), max(1, len(df_chart)//10))
                ],
                tickangle  = -45,
                tickfont   = dict(size=9),
            ),
            yaxis=dict(
                range      = [0, 10],
                dtick      = 2,
                gridcolor  = "#1e2d42",
                gridwidth  = 1,
                title      = "",
            ),
            margin    = dict(l=40, r=20, t=20, b=80),
            showlegend = False,
            hoverlabel = dict(
                bgcolor     = "#111927",
                bordercolor = "#1e2d42",
                font        = dict(family="DM Mono, monospace", size=12, color="#c8d8e8"),
            ),
        )

        st.plotly_chart(fig, use_container_width=True)

        # ── Estadísticas debajo ───────────────────────────────────────────────
        c1, c2, c3 = st.columns(3)
        c1.metric("Promedio", f"{df_historial['nivel'].mean():.1f} / 10")
        c2.metric("Máximo registrado", f"{df_historial['nivel'].max()} / 10")
        c3.metric("Total sesiones", len(df_historial))
    with tab2:
        # Configuramos cada columna explícitamente para que `razon` tenga
        # suficiente espacio y el texto sea legible sin recortes.
        # `width="large"` en TextColumn le asigna la mayor parte del ancho disponible.
        st.dataframe(
            df_historial,
            use_container_width=True,
            hide_index=True,
            height=420,
            column_config={
                "id": st.column_config.NumberColumn(
                    "ID", width="small", format="%d"
                ),
                "fecha": st.column_config.TextColumn(
                    "Fecha", width="medium"
                ),
                "nivel": st.column_config.ProgressColumn(
                    "Nivel",
                    width="small",
                    min_value=0,
                    max_value=10,
                    format="%d",
                ),
                "emocion": st.column_config.TextColumn(
                    "Emoción", width="medium"
                ),
                "razon": st.column_config.TextColumn(
                    "Razón del diagnóstico",
                    width="large",
                    # No hay max_chars aquí — mostramos el texto completo.
                    # El usuario puede hacer clic en cualquier celda para ver
                    # el contenido íntegro en un popover flotante de Streamlit.
                ),
            },
        )

    with tab3:
        col_a, col_b = st.columns([2, 1])
        with col_a:
            opcion = st.selectbox("Selecciona ID:", df_historial['id'])
        with col_b:
            st.write("")
            if st.button("👁️ Ver imagen", use_container_width=True):
                img_bytes = obtener_imagen_por_id(opcion)
                if img_bytes:
                    st.image(img_bytes, caption=f"Análisis ID: {opcion}", width=300)
                    st.download_button(
                        "⬇️ Descargar Foto", img_bytes,
                        f"analisis_{opcion}.jpg", "image/jpeg",
                        use_container_width=True
                    )
else:
    st.markdown("""
    <div style="background:#0d1320; border:1px solid #1e2d42; border-radius:10px;
                padding:30px; text-align:center; color:#5a7a9a;">
        <div style="font-size:30px; margin-bottom:8px; opacity:0.4;">🗄️</div>
        <div style="font-family:'DM Mono',monospace; font-size:12px;
                    text-transform:uppercase; letter-spacing:0.1em;">
            Base de datos vacía — realiza tu primer análisis
        </div>
    </div>
    """, unsafe_allow_html=True)