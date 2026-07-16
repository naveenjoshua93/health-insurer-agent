import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SARVAM_API_KEY = os.environ["SARVAM_API_KEY"]
SARVAM_BASE_URL = "https://api.sarvam.ai"
