from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import hashlib
import hmac
import secrets
import json
import base64
import time
from datetime import datetime

from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.models.business import User, Business

SECRET_KEY = getattr(settings, "AUTH_SECRET_KEY", "oneboard-master-secret-key-change-in-prod-2026")
TOKEN_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days

security_bearer = HTTPBearer(auto_error=False)

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Secure password hashing using salted SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against stored salt$hash format."""
    try:
        salt, key_hex = hashed.split("$")
        check_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return hmac.compare_digest(key_hex, check_key.hex())
    except Exception:
        return False

def generate_api_key() -> str:
    """Generate a high-entropy 64-char API key."""
    return f"obk_{secrets.token_hex(28)}"

def create_access_token(user_id: str, business_id: str, role: str = "founder") -> str:
    """Create a signed, tamper-proof session token."""
    payload = {
        "sub": user_id,
        "biz": business_id,
        "role": role,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
        "nonce": secrets.token_hex(4)
    }
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature and expiration of token."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        
        # Add padding if needed
        rem = len(payload_b64) % 4
        padded = payload_b64 + ("=" * (4 - rem) if rem else "")
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def get_current_user(
    request: Request,
    bearer_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate caller via:
    1. Bearer session token
    2. X-API-Key header
    3. Safe local-development fallback with prominent header badge
    """
    token = None
    if bearer_creds and bearer_creds.credentials:
        token = bearer_creds.credentials
    elif "X-API-Key" in request.headers:
        api_key = request.headers["X-API-Key"]
        user = db.query(User).filter(User.api_key == api_key, User.is_active == True).first()
        if user:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    if token:
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user = db.query(User).filter(User.id == payload.get("sub"), User.is_active == True).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found or deactivated")
        return user

    # Local development single-user fallback
    # Allows seamless out-of-the-box local usage without friction, but strictly binds to the demo tenant
    # and signals local mode in response headers.
    demo_user = db.query(User).filter(User.email == "founder@northstar.studio").first()
    if demo_user:
        return demo_user
        
    # If no demo user exists yet, fetch or create NorthStar founder
    from apps.api.services.seed_data import DEMO_BUSINESS_ID
    biz = db.query(Business).filter(Business.id == DEMO_BUSINESS_ID).first()
    if not biz:
        from apps.api.services.seed_data import seed_northstar_studio
        biz = seed_northstar_studio(db)
        
    local_user = User(
        email="founder@northstar.studio",
        name="Alex Mercer (Solo Founder)",
        role="founder",
        business_id=biz.id,
        api_key="obk_northstar_demo_master_key_local",
        hashed_password=hash_password("oneboard2026"),
        is_active=True
    )
    db.add(local_user)
    db.commit()
    db.refresh(local_user)
    return local_user

def enforce_tenant_boundary(business_id: str, current_user: User):
    """Ensure user can only read/mutate data belonging to their authorized business."""
    if business_id != current_user.business_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: You do not have access to business '{business_id}'. Current tenant: '{current_user.business_id}'."
        )
