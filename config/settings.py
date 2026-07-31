import os
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

TALLY_HOST = os.getenv("TALLY_HOST", "127.0.0.1")
TALLY_PORT = int(os.getenv("TALLY_PORT", "9000"))
TALLY_TIMEOUT = int(os.getenv("TALLY_TIMEOUT", "30"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")
