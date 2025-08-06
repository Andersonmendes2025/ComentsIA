
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

with open("/etc/secrets/encryption_key", "rb") as f:
    FERNET_KEY = f.read().strip()
fernet = Fernet(FERNET_KEY)

def encrypt(text):
    return fernet.encrypt(text.encode()).decode() if text else ""

def decrypt(token):
    return fernet.decrypt(token.encode()).decode() if token else ""
