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
Eres un experto psicologo forense y especialista en FACS (Facial Action Coding System).
Tu trabajo es detectar la TRISTEZA OCULTA o SUTIL. No te dejes engañar por una cara seria.

Salida OBLIGATORIA: Un objeto JSON valido.
Formato: {"nivel": ENTERO_0_AL_10, "razon": "analisis tecnico breve", "emocion_dominante": "texto"}

Instrucciones Tecnicas (Basadas en tus requerimientos):
1.  **Analisis de Ojos:** Busca brillo reducido, parpados superiores caidos o mirada desenfocada.
2.  **Analisis de Boca:** Busca comisuras sutilmente deprimidas (AU15) o labios temblorosos.
3.  **Geometria:** Evalua la simetria vertical.

Escala de Calificacion:
* 0-1: Felicidad inequivoca (Sonrisa Duchenne).
* 2: Neutralidad absoluta (Relax total).
* 3-4: Tristeza Sutil / Apatia (La "cara vacia").
* 5-7: Tristeza Evidente (Rasgos caidos).
* 8-10: Angustia / Llanto.

Reglas de Oro:
1. Si la persona NO esta sonriendo, el nivel DEBE ser 3 o superior.
2. La "ausencia de emocion" a menudo es tristeza reprimida o cansancio. Clasificalo como nivel 3 o 4.
3. Busca micro-expresiones: ¿La mirada esta desenfocada o hacia abajo? Eso es tristeza (Nivel 4+).
4. Analiza la imagen AUNQUE ESTE BORROSA, pixelada o sea de baja calidad.
5. Haz tu mejor estimacion basada en la geometria general de la cara (boca, cejas).
6. NUNCA devuelvas error por "calidad de imagen". Solo devuelve nivel -1 si la imagen es totalmente negra o no es una persona.
7. No incluyas markdown.
"""

# --- CLAVES HARDCODED (Para pruebas rápidas) ---
DEFAULT_GEMINI_KEY = ""
DEFAULT_AZURE_KEY = ""

def consultar_gemini(input_data, api_key):
    clave = api_key if api_key else DEFAULT_GEMINI_KEY
    if not clave: return {"error": "Falta Key Gemini"}

    try:
        genai.configure(api_key=clave)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
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

        response = model.generate_content([SYSTEM_PROMPT, img_pil])
        
        if response.text:
            txt = response.text.strip().replace("```json", "").replace("```", "")
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
            if w < 1024 and h < 1024:
                scale = max(1024/w, 1024/h)
                new_w, new_h = int(w * scale), int(h * scale)
                pil_img = pil_img.resize((new_w, new_h), PIL.Image.BICUBIC)
            elif w > 2048 or h > 2048:
                pil_img.thumbnail((2048, 2048))

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
            max_tokens=2000,
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