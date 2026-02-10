import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import time
import os

NOMBRE_MODELO = 'hand_landmarker.task'

class DetectorGestos:
    def __init__(self):
        # Inicializamos el detector una sola vez para no cargar memoria en cada frame
        if not os.path.exists(NOMBRE_MODELO):
            raise FileNotFoundError(f"Falta el archivo {NOMBRE_MODELO}")

        base_options = python.BaseOptions(model_asset_path=NOMBRE_MODELO)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            running_mode=vision.RunningMode.IMAGE) # Usamos IMAGE para Streamlit frame a frame
        
        self.detector = vision.HandLandmarker.create_from_options(options)

    def dibujar_landmarks(self, imagen, landmarks):
        h, w, _ = imagen.shape
        conexiones = [
            (0,1), (1,2), (2,3), (3,4), (0,5), (5,6), (6,7), (7,8),
            (9,10), (10,11), (11,12), (13,14), (14,15), (15,16),
            (0,17), (17,18), (18,19), (19,20), (5,9), (9,13), (13,17)
        ]
        puntos = []
        for lm in landmarks:
            cx, cy = int(lm.x * w), int(lm.y * h)
            puntos.append((cx, cy))
            cv2.circle(imagen, (cx, cy), 4, (0, 255, 255), -1)
            
        for p1, p2 in conexiones:
            if p1 < len(puntos) and p2 < len(puntos):
                cv2.line(imagen, puntos[p1], puntos[p2], (200, 200, 200), 1)
        return imagen

    def detectar_estado_mano(self, frame_cv2):
        """
        Analiza un frame y devuelve: (frame_dibujado, estado_detectado)
        estado_detectado puede ser: 'PALMA', 'PUNO' o None
        """
        # Convertir a formato MediaPipe
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_cv2)
        
        # Detección
        detection_result = self.detector.detect(mp_image)
        
        estado = None
        
        if detection_result.hand_landmarks:
            landmarks = detection_result.hand_landmarks[0]
            
            # Dibujar sobre el frame original
            self.dibujar_landmarks(frame_cv2, landmarks)
            
            # Lógica de Gestos 
            if self._es_palma_abierta(landmarks):
                estado = "PALMA"
            elif self._es_puno_cerrado(landmarks):
                estado = "PUNO"
                
        return frame_cv2, estado

    def _es_palma_abierta(self, landmarks):
        dedos_abiertos = 0
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]
        
        for i in range(4):
            if landmarks[tips[i]].y < landmarks[pips[i]].y:
                dedos_abiertos += 1
        
        if abs(landmarks[4].x - landmarks[17].x) > 0.15:
            dedos_abiertos += 1
            
        return dedos_abiertos >= 4

    def _es_puno_cerrado(self, landmarks):
        dedos_cerrados = 0
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]
        
        for i in range(4):
            if landmarks[tips[i]].y > landmarks[pips[i]].y:
                dedos_cerrados += 1
        
        return dedos_cerrados >= 3