from dotenv import load_dotenv
import os

load_dotenv()

INFERENCE_SERVER_URL = os.getenv("INFERENCE_SERVER_URL")
