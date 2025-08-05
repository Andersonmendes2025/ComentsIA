
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

FERNET_KEY = os.getenv("FERNET_KEY")
fernet = Fernet(FERNET_KEY)

def encrypt(text):
    return fernet.encrypt(text.encode()).decode() if text else ""

def decrypt(token):
    return fernet.decrypt(token.encode()).decode() if token else ""
