import google.generativeai as genai
# Importamos explícitamente los errores necesarios de OpenAI
from openai import AzureOpenAI, APIConnectionError, APITimeoutError, AuthenticationError
import cv2
import base64
import json
import PIL.Image
import io

import requests # Necesario para el buffer de imagen


# ==========================================
#  PROMPT DE INGENIERÍA (MODO AGRESIVO)
# ==========================================

SYSTEM_PROMPT = """
Eres un experto y especialista en FACS (Facial Action Coding System), con integración en psicología y psiquiatría para detectar emociones subyacentes basadas en evidencia científica, como estudios sobre expresiones faciales en trastornos afectivos (e.g., depresión subclínica según DSM-5, donde microexpresiones y AUs indican biomarcadores de distress emocional sin diagnósticos clínicos).
Tu tarea es detectar tristeza oculta o sutil en expresiones faciales, interpretando con precaución apariencias neutrales o serias que podrían indicar emociones reprimidas, como distress o apatía, sin asumir sesgos automáticos de género, edad o etnia, y considerando contextos psiquiátricos como reducción en expresividad positiva correlacionada con anhedonia.
Salida OBLIGATORIA: Un objeto JSON válido y nada más.
Formato exacto: {"nivel": ENTERO_DEL_0_AL_10, "razon": "análisis técnico breve en una o dos oraciones", "emocion_dominante": "texto descriptivo breve como 'felicidad', 'neutral', 'tristeza sutil' o similar"}
Instrucciones Técnicas:
1. Evaluación Inicial de Emociones Múltiples: Identifica emociones básicas (felicidad, tristeza/inflicidad/distress, ira, sorpresa, miedo, disgusto, contempto, neutralidad) asignando scores relativos aproximados (sumando al 100%) basados en combinaciones de AUs observables. Si tristeza/inflicidad predomina (score > 50% o mayor que el promedio de otras), evalúa completamente sus componentes; de lo contrario, ajusta el nivel proporcionalmente a su presencia secundaria, integrando interacciones emocionales como en depresión mixta.
2. Análisis de Ojos: Evalúa brillo reducido, párpados superiores caídos (AU 5), mirada desenfocada o hacia abajo (AU 1+4), cierre prolongado (AU 43), elevación interna de cejas (AU 1) o fruncimiento (AU 4), como indicadores de tristeza; en contextos psiquiátricos, estos patrones sutiles correlacionan con rumiación. Asigna un sub-score de 0-10 basado en intensidad.
3. Análisis de Boca: Busca comisuras deprimidas (AU 15), labios apretados o temblorosos, ausencia de elevación en mejillas (AU 6 ausente) o tirón de comisuras (AU 12 en felicidad genuina), sonrisa falsa sin arrugas oculares; estudios asocian estos con reducción en reforzamiento positivo en trastornos afectivos. Asigna un sub-score de 0-10 basado en intensidad.
4. Geometría Facial: Analiza simetría vertical, tensión en cejas (AU 1+4 para tristeza), postura general, microexpresiones fugaces y asimetrías para desequilibrios; psiquiátricamente, rigidez puede indicar masking emocional. Asigna un sub-score de 0-10 basado en intensidad.
5. Cálculo del Nivel: Promedia los sub-scores de componentes (ojos, boca, geometría) para el nivel base (redondea al entero más cercano). Si tristeza predomina, usa el promedio directamente; si secundaria, multiplica por su score relativo (normalizado 0-1); eleva ligeramente si patrones coinciden con biomarcadores de distress (e.g., alta AU4+AU15 con baja AU12).
Escala de Calificación (usa como guía estricta):
- 0-1: Felicidad inequívoca (sonrisa Duchenne con elevación de mejillas y arrugas en ojos).
- 2: Neutralidad absoluta (rostro completamente relajado sin tensión).
- 3-4: Tristeza sutil o apatía (expresión 'vacía' con indicios leves de caída).
- 5-7: Tristeza evidente (rasgos caídos notables).
- 8-10: Angustia o llanto inminente (expresiones intensas de dolor emocional).
Directrices Generales:
- Considera la ausencia de sonrisa o expresiones neutrales como posibles señales de emociones reprimidas, como tristeza o cansancio mental, evaluando basado en evidencia visual sin reglas fijas de umbral.
- Busca microexpresiones como mirada desenfocada o hacia abajo para informar tu evaluación, priorizando dinámica temporal.
- Analiza siempre la imagen, incluso si es borrosa, pixelada o de baja calidad, basándote en la geometría facial observable (boca, cejas, ojos).
- Si la imagen es totalmente negra o no muestra una persona clara, usa nivel -1.
- No incluyas markdown, texto adicional ni explicaciones fuera del JSON.
"""

# --- CLAVES HARDCODED (Para pruebas rápidas) ---
DEFAULT_GEMINI_KEY = ""
DEFAULT_AZURE_KEY = ""

def consultar_gemini(input_data, api_key):
    clave = api_key if api_key else DEFAULT_GEMINI_KEY
    if not clave: return {"error": "Falta Key Gemini"}

    try:
        genai.configure(api_key=clave)
        model = genai.GenerativeModel('gemini-2.5-flash',tools=[])
        
        img_pil = None
        if isinstance(input_data, str):
            try:
                response = requests.get(input_data, timeout=10)
                response.raise_for_status()
                img_pil = PIL.Image.open(io.BytesIO(response.content))
            except Exception as e:
                return {"error": f"Error descargando URL: {e}"}
        else:
            img_pil = input_data

        response = model.generate_content([SYSTEM_PROMPT, img_pil],tool_config={"function_calling_config": {"mode": "NONE"}})
        
        if response.text:
            txt = response.text.strip().replace("```json", "").replace("```", "")
            uso = response.usage_metadata
            print(f"[GEMINI TOKENS] Entrada: {uso.prompt_token_count} | "
                                f"Salida: {uso.candidates_token_count} | "
                                f"Total: {uso.total_token_count}")

            return json.loads(txt)
        return {"error": "Sin respuesta de Gemini"}

    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"error": str(e)}

def consultar_azure(input_data, api_key, endpoint, deployment_name="gpt-5-chat", formato_envio="PNG"):
    """
    formato_envio: "PNG" (Lossless, ideal cámara) o "JPEG" (Comprimido, ideal archivos JPG).
    """
    clave = api_key if api_key else DEFAULT_AZURE_KEY
    if not clave or not endpoint: return {"error": "Faltan credenciales Azure"}

    try:
        client = AzureOpenAI(
            api_key=clave, 
            api_version="2024-12-01-preview", 
            azure_endpoint=endpoint,
            timeout=300.0,
            max_retries=1
        )
        
        image_url_content = ""
        
        # CASO A: URL Directa
        if isinstance(input_data, str):
            image_url_content = input_data 
        
        # CASO B: Imagen Local
        else:
            if isinstance(input_data, PIL.Image.Image):
                pil_img = input_data
            else:
                img_rgb = cv2.cvtColor(input_data, cv2.COLOR_BGR2RGB)
                pil_img = PIL.Image.fromarray(img_rgb)

            # --- REDIMENSIÓN SEGURA ---
            # Mantenemos lógica de alta resolución (1024-2048)
            w, h = pil_img.size
            #if w < 1024 and h < 1024:
             #   scale = max(1024/w, 1024/h)
            #    new_w, new_h = int(w * scale), int(h * scale)
            #    pil_img = pil_img.resize((new_w, new_h), PIL.Image.BICUBIC)
            #elif w > 2048 or h > 2048:
            #    pil_img.thumbnail((2048, 2048))
    
            # Solo intervenimos si la imagen es DEMASIADO GRANDE (>1024px en algún lado).
            # Si es pequeña, la dejamos como está — el modelo puede analizarla correctamente
            # sin necesitar que la estiremos artificialmente con píxeles interpolados.
            if w > 1024 or h > 1024:
                pil_img.thumbnail((1024, 1024), PIL.Image.LANCZOS)
            # Si w y h son ≤1024, no hacemos nada y seguimos con la imagen original.
            buffer = io.BytesIO()
            
            # --- SELECCIÓN DE FORMATO ---
            if formato_envio == "JPEG":
                # Guardamos como JPEG alta calidad (95%)
                pil_img.save(buffer, format="JPEG", quality=95)
                mime_type = "image/jpeg"
            else:
                # Guardamos como PNG (Por defecto / Cámara)
                pil_img.save(buffer, format="PNG", optimize=True) 
                mime_type = "image/png"

            b64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            image_url_content = f"data:{mime_type};base64,{b64_str}"

        # Inferencia con Detail HIGH forzado
        response = client.chat.completions.create(
            model=deployment_name, 
            messages=[
                { "role": "system", "content": SYSTEM_PROMPT },
                { "role": "user", "content": [
                    { "type": "text", "text": f"Analiza esta imagen ({formato_envio})." },
                    { 
                        "type": "image_url", 
                        "image_url": { 
                            "url": image_url_content, 
                            "detail": "high"
                        } 
                    }
                ]}
            ],
            max_tokens=200,
            temperature=0.0
        )
        print("Azure Response:", response)
        if response.choices:
            txt = response.choices[0].message.content.strip().replace("```json", "").replace("```", "")
            return json.loads(txt)
        return {"error": "Azure no respondió"}

    except AuthenticationError: return {"error": "Azure 401: Clave incorrecta."}
    except APIConnectionError as e: return {"error": f"Error de Red ({formato_envio}): {str(e)}"}
    except APITimeoutError: return {"error": "Timeout Azure."}
    except Exception as e:
        print(f"Azure Error: {e}")
        return {"error": str(e)}