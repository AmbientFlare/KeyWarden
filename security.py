# security.py
import secrets
import string
import hashlib
import json
import jwt
from datetime import datetime, timedelta
import os
from typing import Dict, Any, Optional
import logging

# Secret key for JWT
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set for JWT authentication")
ALGORITHM = "HS256"

logger = logging.getLogger(__name__)

def create_license_key(key_format: str = "XXXX-XXXX-XXXX-XXXX") -> str:
    """Generate a secure license key based on the specified format"""
    # Format: XXXX-XXXX-XXXX-XXXX where X is alphanumeric by default
    chars = string.ascii_uppercase + string.digits
    
    segments = []
    for segment_template in key_format.split('-'):
        length = len(segment_template)
        segment = ''.join(secrets.choice(chars) for _ in range(length))
        segments.append(segment)
    
    return '-'.join(segments)

def hash_license_key(license_key: str) -> str:
    """Hash a license key for secure storage"""
    return hashlib.sha256(license_key.encode()).hexdigest()

def verify_license_key(stored_hash: str, provided_key: str) -> bool:
    """Verify if a provided license key matches the stored hash"""
    return stored_hash == hash_license_key(provided_key)

def get_hardware_fingerprint(system_info: Dict[str, Any]) -> str:
    """
    Generate a hardware fingerprint based on system information
    """
    logger.debug("Generating Hardware Fingerprint")
    logger.debug(f"Input System Info: {system_info}")
    
    # Extract relevant hardware information
    fingerprint_data = {
        "os_name": system_info.get("os_name", ""),
        "os_version": system_info.get("os_version", ""),
        "python_version": system_info.get("python_version", "")
    }
    
    # Create a stable string representation and hash it
    fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
    fingerprint = hashlib.sha256(fingerprint_str.encode()).hexdigest()
    
    logger.debug(f"Generated Fingerprint: {fingerprint}")
    return fingerprint

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT token for API authentication"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
        
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """Verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticate a user with username and password
    
    In a real application, this would validate against a user database
    """
    # Demo implementation - replace with actual database lookup
    if username == "admin" and password == os.environ.get("ADMIN_PASSWORD", "admin"):
        return {
            "sub": username,
            "role": "admin"
        }
    return None

def generate_api_key(key_type: str = "client") -> str:
    """Generate a new API key with type-specific prefix"""
    # Define prefixes based on key type
    prefixes = {
        "admin": "adm-",
        "client": "usr-"
    }
    
    # Get the appropriate prefix
    prefix = prefixes.get(key_type, "usr-")
    
    # Generate the base key (slightly shorter to account for prefix)
    base_key = secrets.token_urlsafe(24)
    
    # Return prefixed key
    return f"{prefix}{base_key}"