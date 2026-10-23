"""Bank logins typed in the cloud app, sealed for the Mac.

The Mac makes a key pair once: the private key stays in its Keychain, the public key goes
in settings ("robot_public_key"). The app seals username+password with the public key and
stores only that ciphertext ("pending_login:<bank>"); only the Mac can open it. The Mac
saves the login to its Keychain and deletes the row. Plain text never touches the DB.
"""

import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

PUBLIC_KEY = "robot_public_key"
SEEN = "robot_seen"  # {"at": iso time, "banks": [banks with a saved login]}
_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def pending_key(bank: str) -> str:
    return f"pending_login:{bank}"


def new_keypair() -> tuple[str, str]:
    """(private PEM, public PEM)."""
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def seal(public_pem: str, username: str, password: str) -> str:
    """RSA-OAEP fits ~318 bytes with a 3072-bit key, plenty for a bank login."""
    key = serialization.load_pem_public_key(public_pem.encode())
    data = json.dumps({"u": username, "p": password}).encode()
    if len(data) > 300:
        raise ValueError("Username and password are too long.")
    return base64.b64encode(key.encrypt(data, _OAEP)).decode()


def unseal(private_pem: str, sealed: str) -> tuple[str, str]:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    d = json.loads(key.decrypt(base64.b64decode(sealed), _OAEP))
    return d["u"], d["p"]
