import logging
from pydantic import BaseModel
from deepface import DeepFace
from fastapi import FastAPI, HTTPException
import uvicorn
import numpy as np
import requests
import cv2


# --- Setup ---
app = FastAPI(title="Face Verification API")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Model & Constants (Same as before) ---
FACE_MODEL = "ArcFace"
DISTANCE_METRIC = "cosine"
FACE_DETECTOR_BACKEND = "opencv"

logger.info(f"Loading facial model: {FACE_MODEL}...")
DeepFace.build_model(FACE_MODEL)
logger.info("Facial model loaded successfully.")

# --- Pydantic Models for JSON Payloads ---
class DetectFacePayload(BaseModel):
    img: str  # The registered image as a Base64 string

class VerifyFacePayload(BaseModel):
    regimg: str
    verimg: str

# --- Helper function ---
def read_image_from_url(url: str) -> np.ndarray:
    """Downloads an image from a URL into an OpenCV-compatible image."""
    try:
        response = requests.get(url)
        response.raise_for_status() # Raise an error for bad responses (4xx, 5xx)
        # Convert downloaded bytes into numpy array
        nparr = np.frombuffer(response.content, np.uint8)
        # Decode array into OpenCV BGR image
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image from URL.")
        return img
    except Exception as e:
        logger.error(f"Error reading image from URL '{url}': {e}")
        raise HTTPException(status_code=400, detail=f"Could not fetch or read image from URL: {str(e)}")

# --- Internal Verification Logic ---
def perform_verification(regimg: np.ndarray, verimg: str) -> dict:
    """ Runs DeepFace.verify and returns a structured dictionary. """
    try:
        result = DeepFace.verify(
            img1_path=regimg,
            img2_path=verimg,
            model_name=FACE_MODEL,
        )
        return {
            "is_match": bool(result["verified"]),
            "distance": result["distance"],
            "threshold": result["threshold"],
            "time": result["time"]
        }
    except ValueError as e:
        # This catches "Face could not be detected" errors from DeepFace
        logger.warning(f"Verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Face detection error: {str(e)}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# --- API Endpoints ---

# Detect Single Face
@app.post("/detect-face")
async def detect_face(payload: DetectFacePayload):
    """
    Validates that the uploaded image contains EXACTLY one face.
    Returns the facial area and confidence if successful.
    """
    logger.info("Received request for /detect-face")
    
    try:
        # 1. Run Extraction
        # enforce_detection=True raises ValueError if 0 faces are found
        faces = DeepFace.extract_faces(
            img_path=payload.img,
            #anti_spoofing=True
        )
        
        # 2. Check Face Count
        face_count = len(faces)
        
        if face_count > 1:
            logger.warning(f"Detection failed: Found {face_count} faces.")
            raise HTTPException(
                status_code=400, 
                detail=f"Registration failed: Found {face_count} faces. Please provide a photo with exactly one face."
            )

        # 3. Success (Exactly 1 face)
        face_data = faces[0]
        
        # 4. Check Anti-Spoofing Result
        # 'is_real' boolean key is added when anti_spoofing=True
        is_real = face_data.get("is_real", True) 
        antispoof_score = face_data.get("antispoof_score", 0)

        if is_real is False:
            logger.warning(f"Spoof detected! Score: {antispoof_score}")
            raise HTTPException(
                status_code=400,
                detail="Spoof detected. Please provide a live, real photo (no screens or printed photos)."
            )

        # 5. Success
        logger.info("Single real face detected successfully.")
        
        return {
            "status": "success",
            "is_real": is_real,
            "antispoof_score": antispoof_score
        }

    except ValueError as e:
        # DeepFace raises ValueError if 0 faces are found (when enforce_detection=True)
        logger.warning(f"Detection failed: No face found. {e}")
        raise HTTPException(status_code=400, detail="No face detected in the image. Please try again.")
        
    except HTTPException as http_exc:
        raise http_exc
        
    except Exception as e:
        logger.error(f"Unexpected error in /detect-face: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/verify") # NEW URL endpoint
async def verify_face(payload: VerifyFacePayload):
    logger.info("Received request for /verify (JSON)")
    baseimage = read_image_from_url(payload.regimg)
    result = perform_verification(baseimage, payload.verimg)
    return result

if __name__ == "__main__":
    logger.info("Starting face verification service on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
