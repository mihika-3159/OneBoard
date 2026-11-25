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
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import text

from apps.api.core.config import settings
from apps.api.core.database import get_db, scope_tenant_session
from apps.api.models.business import Business, BusinessMembership, LoginThrottleState, User, UserSession

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
elif _DEMO_MODE and not settings.ONEBOARD_PRODUCTION_MODE:
    # Explicit local demo only. Never permit the predictable sentinel when
    # production mode is enabled, even if a demo flag was also set.
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
    """Return a high-entropy API credential (shown once, never persisted raw)."""
    return f"obk_{secrets.token_hex(28)}"


def hash_api_key(api_key: str) -> str:
    """Return a non-authenticating SHA-256 verifier for a high-entropy API key.

    Keys have 224 bits of random entropy. Unlike a password, they do not
    require a slow password KDF: SHA-256 gives constant-time work and prevents
    a database-only leak from immediately authenticating to the API.
    """
    return "sha256:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _valid_api_key_format(value: str) -> bool:
    """Only allow canonical generated keys into production lookup paths."""
    return (
        isinstance(value, str)
        and len(value) == 60
        and value.startswith("obk_")
        and all(ch in "0123456789abcdef" for ch in value[4:])
    )


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
        # Bound attacker-controlled bearer/cookie input before signature and JSON work.
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError("Invalid token size")
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("Malformed token structure")
        payload_b64, sig = parts
        # Accept only the canonical wire representation produced by our issuer.
        if (not payload_b64 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in payload_b64)
                or len(sig) != 64 or any(ch not in "0123456789abcdef" for ch in sig)):
            raise ValueError("Invalid token encoding")
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            previous = settings.AUTH_PREVIOUS_SECRET_KEY
            if len(previous) < 32 or previous == SECRET_KEY or previous == "oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION" or not hmac.compare_digest(sig,hmac.new(previous.encode("utf-8"),payload_b64.encode("utf-8"),hashlib.sha256).hexdigest()):
                raise ValueError("Invalid signature")

        padding = "=" * (4 - len(payload_b64) % 4)
        decoded = base64.b64decode(payload_b64 + padding, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != payload_b64:
            raise ValueError("Noncanonical token encoding")
        def unique_claims(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate token claim")
                result[key] = value
            return result
        payload = json.loads(decoded.decode("utf-8"), object_pairs_hook=unique_claims)

        # A valid HMAC alone does not make the signed claims well-formed.
        # Reject missing, malformed, or non-expiring identity/time claims.
        if not isinstance(payload, dict):
            raise ValueError("Invalid token payload")
        for field in ("jti", "sub", "biz"):
            value = payload.get(field)
            if not isinstance(value, str) or not value or len(value) > 255:
                raise ValueError("Invalid token identity claim")
        for field in ("exp", "iat"):
            value = payload.get(field)
            if type(value) is not int or value < 0:
                raise ValueError("Invalid token time claim")
        now = int(time.time())
        if (payload["exp"] <= now or payload["iat"] > now + 60
                or payload["iat"] > payload["exp"]
                or payload["exp"] - payload["iat"] > TOKEN_EXPIRY_SECONDS):
            raise ValueError("Expired or invalid token lifetime")

        return payload
    except Exception as exc:
        raise ValueError("Invalid access token") from exc


# ---------------------------------------------------------------------------
# Login Throttling / Rate Limiting
# ---------------------------------------------------------------------------
# Development/test-only legacy helper for unit tests without a DB session.
# Real login endpoints ALWAYS pass their DB session. Production fails closed if
# a caller attempts to use this process-local fallback.
_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}


def _throttle_key(identifier: str) -> str:
    # Do not store raw client IP addresses or email addresses in the throttle table.
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _lock_shared_throttle(db: Session, identifier: str) -> None:
    """Serialize updates for this identifier across PostgreSQL API workers.

    The caller's transaction must remain open from check through record/reset.
    For PostgreSQL this is a transaction-scoped advisory lock, including the
    previously missing-row case. SQLite is supported only for isolated tests.
    """
    if db.get_bind().dialect.name == "postgresql":
        lock_id = int.from_bytes(
            hashlib.sha256(identifier.encode("utf-8")).digest()[:8],
            byteorder="big", signed=True,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


def check_login_throttle(identifier: str, db: Optional[Session] = None) -> None:
    """Reject another attempt after too many recent failures.

    When a DB session is supplied, the advisory lock is intentionally kept
    until record_failed_login/reset_login_throttle commits the transaction.
    This avoids a check-then-insert race across PostgreSQL workers.
    """
    now = time.time()
    window = settings.LOGIN_LOCKOUT_SECONDS
    # Registration is source-wide and counts successful signups too, while
    # login throttling is scoped to source+account or account. Reusing the
    # five-guess login budget for a whole NAT wrongly locks out unrelated
    # school/office users. Keep both budgets independently bounded.
    max_attempts = (
        settings.AUTH_GLOBAL_ATTEMPTS
        if identifier == "global-auth-admission"
        else settings.REGISTRATION_SOURCE_MAX_ATTEMPTS
        if identifier.startswith("registration-source:")
        else settings.LOGIN_SOURCE_MAX_ATTEMPTS
        if identifier.startswith("login-source:")
        else settings.LOGIN_MAX_ATTEMPTS
    )

    if db is not None:
        _lock_shared_throttle(db, identifier)
        state = db.query(LoginThrottleState).filter(
            LoginThrottleState.identifier_hash == _throttle_key(identifier)
        ).first()
        if state is None or now - state.window_started_at >= window:
            return
        attempts_count = state.attempt_count
        first_attempt = state.window_started_at
    else:
        if settings.ONEBOARD_PRODUCTION_MODE:
            raise RuntimeError("Production login throttling requires a shared DB session")
        attempts = [t for t in _LOGIN_ATTEMPTS.get(identifier, []) if now - t < window]
        _LOGIN_ATTEMPTS[identifier] = attempts
        attempts_count = len(attempts)
        first_attempt = attempts[0] if attempts else now

    if attempts_count >= max_attempts:
        retry_after = max(int(window - (now - first_attempt)), 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )


def record_failed_login(identifier: str, db: Optional[Session] = None) -> None:
    """Persist a failed attempt. This must close the shared-check transaction."""
    now = time.time()
    if db is None:
        if settings.ONEBOARD_PRODUCTION_MODE:
            raise RuntimeError("Production login throttling requires a shared DB session")
        _LOGIN_ATTEMPTS.setdefault(identifier, []).append(now)
        return

    _lock_shared_throttle(db, identifier)
    key = _throttle_key(identifier)
    state = db.query(LoginThrottleState).filter(
        LoginThrottleState.identifier_hash == key
    ).first()
    if state is None:
        state = LoginThrottleState(identifier_hash=key, window_started_at=now, attempt_count=1)
        db.add(state)
    elif now - state.window_started_at >= settings.LOGIN_LOCKOUT_SECONDS:
        state.window_started_at = now
        state.attempt_count = 1
    else:
        state.attempt_count += 1
    db.commit()


def reset_login_throttle(identifier: str, db: Optional[Session] = None, *, commit: bool = True) -> None:
    """Clear the counter after valid login, across every server process."""
    if db is None:
        if settings.ONEBOARD_PRODUCTION_MODE:
            raise RuntimeError("Production login throttling requires a shared DB session")
        _LOGIN_ATTEMPTS.pop(identifier, None)
        return
    _lock_shared_throttle(db, identifier)
    db.query(LoginThrottleState).filter(
        LoginThrottleState.identifier_hash == _throttle_key(identifier)
    ).delete(synchronize_session=False)
    if commit:
        db.commit()


# ---------------------------------------------------------------------------
# CSRF Protection
# ---------------------------------------------------------------------------
def verify_session_issuance_origin(request: Request) -> None:
    """Protect browser login/registration against cross-site session swapping.

    Non-browser API clients can still request bearer credentials without an
    Origin. The explicit browser cookie mode requires the configured origin
    in production, including before a session cookie exists.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    browser_mode = request.headers.get("X-OneBoard-Session-Mode") == "cookie"
    if not origin and referer:
        try:
            parsed = urlsplit(referer)
            if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Invalid referer")
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except ValueError:
            raise HTTPException(403, "Untrusted authentication origin") from None
    allowed = {item.strip() for item in settings.CORS_ORIGINS.split(",") if item.strip()}
    if (origin and origin not in allowed) or (
        settings.ONEBOARD_PRODUCTION_MODE and browser_mode and not origin
    ):
        raise HTTPException(403, "Untrusted authentication origin")


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

    # Check the exact origin. If Origin is absent, use the Referer origin;
    # in production, a cookie-authenticated mutation must provide one.
    if origin:
        request_origin = origin
    elif referer:
        try:
            parsed = urlsplit(referer)
            if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Malformed referer")
            request_origin = f"{parsed.scheme}://{parsed.netloc}"
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF origin check failed: untrusted origin."
            ) from None
    else:
        request_origin = None

    if (request_origin and request_origin not in allowed_origins) or (
        settings.ONEBOARD_PRODUCTION_MODE and not request_origin
    ):
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
    # Deletion takes the exclusive lifecycle lock from its first scoped
    # transaction; concurrent deleters must not upgrade two shared locks.
    path=getattr(getattr(request,"url",None),"path",None) or ""
    if isinstance(db, Session) and (path in ("/api/data/delete-workspace","/api/data/portable/restore") or (path.startswith("/api/auth/security/") and request.method in ("POST","PUT","DELETE"))):
        db.info["oneboard_exclusive_lifecycle"] = True
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
                detail="Invalid or expired authentication credentials.",
                headers={"WWW-Authenticate": "Bearer"}
            )

        jti = payload.get("jti")
        user_id = payload.get("sub")
        from apps.api.core.tenant_context import restricted
        if restricted(db):
            scope_tenant_session(db,payload["biz"])

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
                if session_record.expires_at <= datetime.utcnow():
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
        _require_active_membership(user, db)
        if isinstance(db,Session):
            db.info['oneboard_auth']=(user.id,jti,None)
        scope_tenant_session(db, user.business_id)
        return user

    # 2. X-API-Key Header Authentication
    api_key = request.headers.get("x-api-key")
    if api_key:
        invalid_key = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key provided.",
            headers={"WWW-Authenticate": "ApiKey"}
        )
        # Bound input and deny noncanonical credentials before SQL work.
        if not _valid_api_key_format(api_key):
            if settings.ONEBOARD_PRODUCTION_MODE or not (
                api_key.startswith("obk_") and len(api_key) <= 100
            ):
                raise invalid_key
        # Production never compares a raw API key against stored secrets.
        from apps.api.core.tenant_context import restricted,lookup
        if restricted(db):
            found=lookup(db,"key",hash_api_key(api_key))
            if not found:
                raise invalid_key
            scope_tenant_session(db,found.tenant)
        if restricted(db):
            user=db.query(User).filter_by(id=found.uid,business_id=found.tenant,is_active=True).first()
        else:
            user = db.query(User).filter(
                User.api_key == hash_api_key(api_key),
                User.is_active == True,
            ).first()
        if user is None and not settings.ONEBOARD_PRODUCTION_MODE:
            # Development-only support for legacy, locally seeded demo keys.
            user = db.query(User).filter(
                User.api_key == api_key, User.is_active == True
            ).first()
        if user:
            _require_active_membership(user, db)
            if isinstance(db,Session):
                from apps.api.services.account_security import check_api_key_permissions
                scope_tenant_session(db,user.business_id)
                check_api_key_permissions(db,user,request)
                db.info['oneboard_api_key']=True
            if isinstance(db,Session) and settings.ONEBOARD_PRODUCTION_MODE:
                db.info['oneboard_auth']=(user.id,None,hash_api_key(api_key))
            scope_tenant_session(db, user.business_id)
            return user
        raise invalid_key

    # 3. Demo / Local Dev Fallback (Opt-in only, never synthesised on the fly)
    if _DEMO_MODE and not settings.ONEBOARD_PRODUCTION_MODE:
        from apps.api.services.seed_data import DEMO_BUSINESS_ID
        demo_user = (
            db.query(User)
            .filter(User.business_id == DEMO_BUSINESS_ID, User.is_active == True)
            .first()
        )
        if demo_user:
            scope_tenant_session(db, demo_user.business_id)
            return demo_user

    # 4. Fail Closed: Unauthenticated
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid session cookie, Bearer token, or X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"}
    )


def enforce_tenant_boundary(resource_business_id: str, current_user: User, db: Optional[Session] = None) -> None:
    """Enforce the single active-tenant context used by every API router.

    A secondary BusinessMembership must *not* grant access to resource IDs
    outside the user's active business. Routers and workflow services always
    execute in current_user.business_id, not an explicitly switched context.
    Accepting secondary memberships here caused confused-deputy access.
    Keep the db parameter for existing call sites, but never use it to widen
    the authorized tenant.
    """
    if not resource_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing resource business context."
        )
    if resource_business_id != current_user.business_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Access to another business tenant's resources is denied."
        )


def _require_active_membership(user: User, db: Session) -> None:
    """Deny revoked production workspace access even for valid signed tokens.

    Registration creates an owner membership. Legacy owner rows are recognized
    by the business owner_id, but a non-owner without a matching membership is
    no longer authorized. This applies to API keys as well as signed sessions;
    disabling a user, deleting their membership, or changing their primary
    tenant must never leave a working credential to that tenant.
    """
    if not settings.ONEBOARD_PRODUCTION_MODE:
        return
    business = db.query(Business).filter(Business.id == user.business_id).first()
    if business is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Workspace access has been revoked."
        )
    if business.owner_id == user.id:
        return
    membership = db.query(BusinessMembership).filter(
        BusinessMembership.user_id == user.id,
        BusinessMembership.business_id == user.business_id
    ).first()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Workspace access has been revoked."
        )


def require_founder_role(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Authorize privileged mutations using live production membership roles.

    A persisted User.role alone is insufficient: demoting a membership from
    founder to member must immediately remove write/approval privileges from
    already-issued sessions and API keys. The business owner is independently
    authorized through the live ownership record.
    """
    forbidden = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: This operation requires founder privileges."
    )
    if current_user.role not in ("founder", "admin", "owner"):
        raise forbidden
    if settings.ONEBOARD_PRODUCTION_MODE:
        business = db.query(Business).filter(Business.id == current_user.business_id).first()
        if business is None:
            raise forbidden
        if business.owner_id != current_user.id:
            membership = db.query(BusinessMembership).filter(
                BusinessMembership.user_id == current_user.id,
                BusinessMembership.business_id == current_user.business_id,
            ).first()
            if membership is None or membership.role not in ("founder", "admin", "owner"):
                raise forbidden
    if isinstance(db,Session) and settings.ONEBOARD_PRODUCTION_MODE:
        db.info['oneboard_founder']=True
        if db.info.get('oneboard_request'):
            scope_tenant_session(db,current_user.business_id)
    return current_user
