"""
OneBoard Centralized Authentication and Tenant Authorization Module.

Features:
- Passwords hashed using Argon2id (never plaintext).
- Cryptographic session tokens with HMAC-SHA256 signatures and expiration.
- Server-side session tracking and instant logout revocation via UserSession records.
- HttpOnly, SameSite cookies with configurable Secure flag in HTTPS deployments.
- CSRF validation for cookie-authenticated state-changing requests.
- Rate limiting / login throttling against brute-force attacks.
- Fail-closed security: requires AUTH_SECRET_KEY; demo mode is opt-in only.
- Strict multi-tenant boundary enforcement scoping all data access to authorized business_id.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.models.business import Business, BusinessMembership, User, UserSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Argon2id Password Hasher
# ---------------------------------------------------------------------------
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16
)


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against Argon2id hash (with legacy PBKDF2 fallback if needed)."""
    if not hashed or not password:
        return False
    try:
        if hashed.startswith("$argon2"):
            return _ph.verify(hashed, password)
        # Legacy PBKDF2 fallback support for old demo records if any
        if "$" in hashed:
            salt, key_hex = hashed.split("$", 1)
            check_key = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
            )
            return hmac.compare_digest(key_hex, check_key.hex())
        return False
    except (VerifyMismatchError, VerificationError, InvalidHashError, Exception):
        return False


# ---------------------------------------------------------------------------
# Secret Key Configuration (Fail Closed)
# ---------------------------------------------------------------------------
_ENV_SECRET = os.environ.get("AUTH_SECRET_KEY") or settings.AUTH_SECRET_KEY
_DEMO_MODE: bool = (
    os.environ.get("ONEBOARD_DEMO_MODE", "").lower() in ("1", "true", "yes")
    or settings.ONEBOARD_DEMO_MODE
)

if _ENV_SECRET:
    SECRET_KEY: str = _ENV_SECRET
elif _DEMO_MODE:
    # Explicit demo mode: allow local-only development sentinel
    SECRET_KEY = "oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION"
else:
    raise RuntimeError(
        "AUTH_SECRET_KEY environment variable is not set and ONEBOARD_DEMO_MODE is not enabled. "
        "Set AUTH_SECRET_KEY to a securely generated random value, or set "
        "ONEBOARD_DEMO_MODE=true for local development only."
    )

TOKEN_EXPIRY_SECONDS = settings.SESSION_EXPIRY_SECONDS
SESSION_COOKIE_NAME = "oneboard_session"
CSRF_COOKIE_NAME = "oneboard_csrf"
CSRF_HEADER_NAME = "x-csrf-token"

security_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# API Key Utilities
# ---------------------------------------------------------------------------
def generate_api_key() -> str:
    """Return a high-entropy 64-character API key with the 'obk_' prefix."""
    return f"obk_{secrets.token_hex(28)}"


def generate_csrf_token() -> str:
    """Generate high-entropy CSRF token."""
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Session Token Utilities (HMAC-SHA256 Signed JSON)
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    business_id: str,
    role: str = "founder",
    jti: Optional[str] = None
) -> str:
    """Mint an HMAC-SHA256 signed bearer / session token."""
    session_id = jti or secrets.token_hex(16)
    payload = {
        "jti": session_id,
        "sub": user_id,
        "biz": business_id,
        "role": role,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
        "iat": int(time.time()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(
        SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and cryptographically verify an access token."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("Malformed token structure")
        payload_b64, sig = parts
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Invalid signature")

        padding = "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((payload_b64 + padding).encode("utf-8")).decode("utf-8")
        )

        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("Token expired")

        return payload
    except Exception as exc:
        raise ValueError(f"Invalid access token: {exc}") from exc


# ---------------------------------------------------------------------------
# Login Throttling / Rate Limiting
# ---------------------------------------------------------------------------
# Sliding window: { identifier: [timestamp, ...] }
_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}


def check_login_throttle(identifier: str) -> None:
    """Enforce login attempt rate limiting to mitigate password brute-forcing."""
    now = time.time()
    window = settings.LOGIN_LOCKOUT_SECONDS
    max_attempts = settings.LOGIN_MAX_ATTEMPTS

    attempts = [t for t in _LOGIN_ATTEMPTS.get(identifier, []) if now - t < window]
    _LOGIN_ATTEMPTS[identifier] = attempts

    if len(attempts) >= max_attempts:
        retry_after = int(window - (now - attempts[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please try again in {max(retry_after, 1)} seconds.",
            headers={"Retry-After": str(max(retry_after, 1))}
        )


def record_failed_login(identifier: str) -> None:
    """Record a failed login attempt for the given identifier."""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.setdefault(identifier, [])
    attempts.append(now)


def reset_login_throttle(identifier: str) -> None:
    """Reset failed login attempts upon successful authentication."""
    _LOGIN_ATTEMPTS.pop(identifier, None)


# ---------------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------------
def verify_csrf_protection(request: Request) -> None:
    """
    Validate CSRF token for cookie-authenticated state-changing requests.
    Bearer tokens and X-API-Key authentication are exempt since browsers do
    not send custom headers automatically cross-origin.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Check if this request is using cookie-based authentication
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        # Not using cookie auth (e.g. Authorization Bearer or API Key)
        return

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    csrf_header = request.headers.get(CSRF_HEADER_NAME)

    # Validate Origin / Referer against CORS allowlist
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    allowed_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

    if origin and allowed_origins:
        if origin not in allowed_origins and "*" not in allowed_origins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF origin check failed: untrusted origin."
            )

    # Double submit cookie check if csrf cookie or header is provided
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch or missing X-CSRF-Token header."
        )


# ---------------------------------------------------------------------------
# Cookie Session Helpers
# ---------------------------------------------------------------------------
def set_auth_cookies(
    response: Response,
    token: str,
    csrf_token: Optional[str] = None
) -> None:
    """Set secure HttpOnly session cookie and CSRF cookie."""
    secure_flag = settings.COOKIE_SECURE
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=TOKEN_EXPIRY_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/"
    )
    csrf = csrf_token or generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        max_age=TOKEN_EXPIRY_SECONDS,
        httponly=False,  # Accessible to client JS for setting X-CSRF-Token header
        samesite="lax",
        secure=secure_flag,
        path="/"
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear session and CSRF cookies on logout."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")


# ---------------------------------------------------------------------------
# Central Authentication Dependencies
# ---------------------------------------------------------------------------
def get_current_user(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db)
) -> User:
    """
    Central authentication dependency.
    Extracts credentials in order of precedence:
      1. Authorization: Bearer <token>
      2. Cookie: oneboard_session=<token>
      3. Header: X-API-Key: obk_<key>
    Validates token signature, expiration, and database session revocation.
    Fails closed with HTTP 401 when unauthenticated.
    """
    token: Optional[str] = None
    if bearer and bearer.credentials:
        token = bearer.credentials
    elif SESSION_COOKIE_NAME in request.cookies:
        token = request.cookies[SESSION_COOKIE_NAME]
        # Perform CSRF check on cookie-authenticated mutations
        verify_csrf_protection(request)

    # 1. Bearer / Cookie Token Authentication
    if token:
        try:
            payload = decode_access_token(token)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired authentication credentials: {err}",
                headers={"WWW-Authenticate": "Bearer"}
            )

        jti = payload.get("jti")
        user_id = payload.get("sub")

        # Verify session revocation in database if jti is present
        if jti:
            session_record = db.query(UserSession).filter(UserSession.id == jti).first()
            if not session_record or session_record.user_id != user_id or session_record.business_id != payload.get("biz"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or mismatched session.")
            if session_record:
                if session_record.is_revoked:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session has been revoked. Please log in again.",
                        headers={"WWW-Authenticate": "Bearer"}
                    )
                if session_record.expires_at < datetime.utcnow():
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session has expired. Please log in again.",
                        headers={"WWW-Authenticate": "Bearer"}
                    )

        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account associated with this session no longer exists or is inactive.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        if user.business_id != payload.get("biz"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session tenant mismatch.")
        return user

    # 2. X-API-Key Header Authentication
    api_key = request.headers.get("x-api-key")
    if api_key:
        user = db.query(User).filter(User.api_key == api_key, User.is_active == True).first()
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key provided.",
            headers={"WWW-Authenticate": "ApiKey"}
        )

    # 3. Demo / Local Dev Fallback (Opt-in only, never synthesised on the fly)
    if _DEMO_MODE:
        from apps.api.services.seed_data import DEMO_BUSINESS_ID
        demo_user = (
            db.query(User)
            .filter(User.business_id == DEMO_BUSINESS_ID, User.is_active == True)
            .first()
        )
        if demo_user:
            return demo_user

    # 4. Fail Closed: Unauthenticated
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid session cookie, Bearer token, or X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"}
    )


def enforce_tenant_boundary(resource_business_id: str, current_user: User, db: Optional[Session] = None) -> None:
    """
    Object-level authorization check.
    Ensures that current_user is an authorized member/owner of resource_business_id.
    """
    if not resource_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing resource business context."
        )

    if current_user.business_id == resource_business_id:
        return

    # Secondary check in BusinessMembership table if db session provided
    if db:
        membership = db.query(BusinessMembership).filter(
            BusinessMembership.user_id == current_user.id,
            BusinessMembership.business_id == resource_business_id
        ).first()
        if membership:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: Access to another business tenant's resources is denied."
    )


def require_founder_role(current_user: User = Depends(get_current_user)) -> User:
    """Ensure the authenticated user has founder or admin permissions."""
    if current_user.role not in ("founder", "admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This operation requires founder privileges."
        )
    return current_user
