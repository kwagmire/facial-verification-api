import logging
from pydantic import BaseModel
from deepface import DeepFace
from fastapi import FastAPI, HTTPException
import uvicorn
import numpy as np
import requests
import cv2
import base64

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

def read_image_from_base64(b64_string: str) -> np.ndarray:
    """Decodes a Base64 string into an OpenCV-compatible image."""
    try:
        # Check/Remove Data URI prefix if present
        if "," in b64_string:
            b64_string = b64_string.split(",")[1]
            
        img_bytes = base64.b64decode(b64_string)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image from Base64 string.")
        return img
    except Exception as e:
        logger.error(f"Error reading Base64 image: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid Base64 image: {str(e)}")

# --- Internal Verification Logic ---
def perform_verification(regimg: np.ndarray, verimg: np.ndarray) -> dict:
    """ Runs DeepFace.verify and returns a structured dictionary. """
    
    ver_img_height = verimg.shape[0]
    
    try:
        result = DeepFace.verify(
            img1_path=regimg,
            img2_path=verimg,
            model_name=FACE_MODEL,
            anti_spoofing=True
        )

        # 3. Check Face/Image Ratio on Verification Image (img2)
        facial_areas = result.get("facial_areas", {})
        img2_area = facial_areas.get("img2", {})
        face_height = img2_area.get("h", 0)
        
        if face_height > 0:
            ratio = face_height / ver_img_height
            logger.info(f"Verification Image - ImgH: {ver_img_height}, FaceH: {face_height}, Ratio: {ratio:.2f}")
            
            if ratio < 0.50:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Face is too small ({int(ratio*100)}%). Please move closer (target: 50%+)."
                )

        return {
            "is_match": bool(result["verified"]),
            "distance": result["distance"],
            "threshold": result["threshold"],
            "time": result["time"],
            "ratio": round(ratio, 2)
        }

    except ValueError as e:
        # This catches "Face could not be detected" errors from DeepFace
        logger.warning(f"Verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Face detection error: {str(e)}")
    except HTTPException as he:
        raise he
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

    # 1. Decode first to get image dimensions
    img_arr = read_image_from_base64(payload.img)
    img_height, img_width, _ = img_arr.shape
    
    try:
        # 1. Run Extraction
        # enforce_detection=True raises ValueError if 0 faces are found
        faces = DeepFace.extract_faces(
            img_path=img_arr,
            anti_spoofing=True
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
        
        # 4. Check Size (Face Height vs Image Height)
        facial_area = face_data.get("facial_area", {})
        face_height = facial_area.get("h", 0)
        
        height_ratio = face_height / img_height
        MIN_HEIGHT_RATIO = 0.50 # 50%

        logger.info(f"ImgH: {img_height}, FaceH: {face_height}, Ratio: {height_ratio:.2f}")

        if height_ratio < MIN_HEIGHT_RATIO:
            raise HTTPException(
                status_code=400,
                detail=f"Face is too small/far away ({int(height_ratio*100)}%). Please move closer (target: 50%+)."
            )

        # 5. Success
        logger.info("Single real face detected successfully.")
        
        return {
            "status": "success",
            "is_real": is_real,
            "antispoof_score": antispoof_score,
            "face_height_ratio": round(height_ratio, 2)
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
    ver_arr = read_image_from_base64(payload.verimg)

    result = perform_verification(baseimage, ver_arr)
    return result

if __name__ == "__main__":
    logger.info("Starting face verification service on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
