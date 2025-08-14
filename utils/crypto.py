# utils/crypto.py
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv() 
def _load_key_bytes():
    path = os.getenv("ENCRYPTION_KEY_PATH", "/etc/secrets/encryption_key")
    key = None
    if path and os.path.exists(path):
        key = open(path, "rb").read().strip()
    else:
        env = os.getenv("ENCRYPTION_KEY", "")
        key = env.encode() if env else None
    if not key or len(key) != 44:
        raise RuntimeError("Chave Fernet inválida ou ausente (espera 44 chars base64, termina com '=')")
    return key

FERNET = Fernet(_load_key_bytes())

# Fallback opcional (se tiver a chave antiga)
OLD = os.getenv("OLD_ENCRYPTION_KEY")
FERNET_OLD = Fernet(OLD.encode()) if OLD else None

def encrypt(text: str) -> str:
    return FERNET.encrypt(text.encode()).decode() if text else ""

def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return FERNET.decrypt(token.encode()).decode()
    except Exception:
        if FERNET_OLD:
            try:
                return FERNET_OLD.decrypt(token.encode()).decode()
            except Exception:
                pass
        raise  # deixa explodir para você ver que a chave não bate
