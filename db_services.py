import sqlite3
import io
from datetime import datetime
import pandas as pd

# Nombre del archivo donde se guardará todo
DB_NAME = "historial_dar.db"

def init_db():
    """
    Crea la tabla si no existe.
    Estructura: ID, Fecha, Nivel, Emoción, Razón, Imagen (BLOB)
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS analisis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            nivel INTEGER NOT NULL,
            emocion TEXT,
            razon TEXT,
            imagen_blob BLOB
        )
    ''')
    conn.commit()
    conn.close()

def guardar_registro(nivel, emocion, razon, imagen_bytes):
    """
    Guarda un nuevo análisis y la foto en la base de datos.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Insertamos los datos. La imagen entra como bytes puros.
    c.execute('''
        INSERT INTO analisis (fecha, nivel, emocion, razon, imagen_blob)
        VALUES (?, ?, ?, ?, ?)
    ''', (fecha_actual, nivel, emocion, razon, imagen_bytes))
    
    conn.commit()
    conn.close()
    print(f"✅ Registro guardado en DB: {fecha_actual}")

def obtener_historial():
    """
    Recupera todos los registros para mostrarlos en la tabla.
    Excluimos la imagen blob de la consulta principal para no hacerla lenta.
    """
    conn = sqlite3.connect(DB_NAME)
    # Leemos con Pandas para facilitar la visualización en Streamlit
    query = "SELECT id, fecha, nivel, emocion, razon FROM analisis ORDER BY id DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def obtener_imagen_por_id(id_registro):
    """
    Recupera solo la imagen de un registro específico para descargarla.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT imagen_blob FROM analisis WHERE id = ?", (id_registro,))
    data = c.fetchone()
    conn.close()
    
    if data:
        return data[0] # Retorna los bytes de la imagen
    return None