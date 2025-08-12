from dotenv import load_dotenv
import os

load_dotenv()

INFERENCE_SERVER_URL = os.getenv("INFERENCE_SERVER_URL")
INCIDENT_WINDOW = 10
UPLOAD_SECRET = os.getenv("UPLOAD_SECRET", "").encode()
UPLOAD_URL = os.getenv("UPLOAD_URL")
