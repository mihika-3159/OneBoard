"""
Authentication router: Founder registration, login, logout, session verification, and API key management.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.core.auth import (
    _require_active_membership,
    TOKEN_EXPIRY_SECONDS,
    check_login_throttle,
    clear_auth_cookies,
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_csrf_token,
    get_current_user,
    hash_password,
    hash_api_key,
    record_failed_login,
    reset_login_throttle,
    set_auth_cookies,
    verify_password,
    verify_csrf_protection,
)
from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.models.business import Business, BusinessMembership, User, UserSession

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=1024)
    business_name: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default="B2B SaaS", max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    mfa_code: Optional[str] = Field(default=None,max_length=64,repr=False)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Register a new founder account, business entity, and server-side membership."""
    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )

    clean_email = req.email.strip().lower()

    # Registration is an expensive anonymous write path: Argon2id hashing,
    # workspace creation, and initial session issuance. Production must rate
    # limit the transport source *across different email addresses*, before
    # any password hashing or database writes. The existing shared PostgreSQL
    # advisory-lock throttle serializes check+record across API workers.
    #
    # This is a conservative per-source budget; shared NATs may exhaust it.
    # Never trust X-Forwarded-For supplied directly by the client.
    if settings.ONEBOARD_PRODUCTION_MODE:
        if not request.client or not request.client.host:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Registration requires a verified client transport address."
            )
        source_key = f"registration-source:{request.client.host}"
        check_login_throttle(source_key, db)
        # Count ALL admitted attempts (including duplicates and failures).
        # This commits the counter *before* a costly hash or account creation,
        # so a failed transaction cannot silently reset the abuse budget.
        record_failed_login(source_key, db)

    existing_user = db.query(User).filter(User.email == clean_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists."
        )

    biz_name = (req.business_name or f"{req.name}'s Studio").strip()
    if not biz_name or len(biz_name) > 255:
        raise HTTPException(status_code=422, detail="Business name must be between 1 and 255 characters")
    business = Business(
        name=biz_name,
        industry=req.industry or "B2B SaaS",
        # Real accounts start without fabricated financial history.
        current_cash_balance=0.0,
        monthly_burn_rate=0.0,
        runway_months=0.0
    )
    db.add(business)
    db.flush()

    hashed_pw = hash_password(req.password)
    user = User(
        email=clean_email,
        name=req.name.strip(),
        hashed_password=hashed_pw,
        role="founder",
        business_id=business.id,
        api_key=hash_api_key(generate_api_key()),
        is_active=True
    )
    db.add(user)
    db.flush()

    # Link business ownership and membership
    business.owner_id = user.id
    membership = BusinessMembership(
        user_id=user.id,
        business_id=business.id,
        role="owner"
    )
    db.add(membership)

    # Create active session record
    session_id = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        business_id=business.id,
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(user_session)
    # Commit the business, owner, membership and session as one unit.
    # Any failure must not leave an orphan workspace or account behind.
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    token = create_access_token(
        user_id=user.id,
        business_id=business.id,
        role=user.role,
        jti=session_id
    )
    csrf_token = generate_csrf_token()
    set_auth_cookies(response, token, csrf_token)

    return {
        "status": "success",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "business_id": user.business_id,
        },
        "business": {
            "id": business.id,
            "name": business.name,
            "industry": business.industry,
            "current_cash_balance": business.current_cash_balance
        },
        "token": token,
        "csrf_token": csrf_token
    }


@router.post("/login")
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Authenticate founder credentials with Argon2id and issue session cookie and token."""
    # The source+account key stops repeated guesses from one address without
    # allowing a different account at that address to clear the counter.
    # Never trust a client-supplied X-Forwarded-For header here: Request.client
    # must be set by the server and a separately configured trusted proxy.
    clean_email = req.email.strip().lower()
    account_key = f"account:{clean_email}"
    source_host = request.client.host if request.client and request.client.host else None
    if settings.ONEBOARD_PRODUCTION_MODE and not source_host:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login requires a verified client transport address.",
        )
    source_host = source_host or "unknown"
    source_key = f"source-account:{source_host}:{clean_email}"

    if settings.ONEBOARD_PRODUCTION_MODE:
        # Charge every admitted attempt *before* user lookup and expensive
        # Argon2 verification. The shared source counter is not reset by a
        # successful login: otherwise valid credentials could continuously
        # clear the budget while guessing passwords for other accounts.
        # This counter is independent of account-specific lockouts and
        # applies when an attacker rotates email addresses behind one IP.
        shared_source_key = f"login-source:{source_host}"
        check_login_throttle(shared_source_key, db)
        record_failed_login(shared_source_key, db)

    # Throttle expensive password verification by source first. Its DB advisory
    # lock stays held until the successful reset or failed-attempt commit.
    check_login_throttle(source_key, db)
    user = db.query(User).filter(User.email == clean_email).first()
    valid_credentials = (
        user is not None
        and verify_password(req.password, user.hashed_password)
        and user.is_active
    )
    if valid_credentials:
        # A revoked membership must not mint a fresh signed session merely
        # because the user's password is still correct. Return the same
        # response as an invalid password and preserve failed-login throttling.
        try:
            _require_active_membership(user, db)
            from apps.api.core.database import scope_tenant_session
            from apps.api.services.account_security import verify_factor
            scope_tenant_session(db,user.business_id)
            if not verify_factor(db,user,req.mfa_code):
                valid_credentials=False
        except HTTPException:
            valid_credentials = False

    if not valid_credentials:
        # Persist a source-scoped failure before attempting the account-wide
        # check. Distributed wrong-password guesses still share account state.
        record_failed_login(source_key, db)
        check_login_throttle(account_key, db)
        record_failed_login(account_key, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # A verified password can recover an account even after attackers exhaust
    # the account-wide wrong-password budget from rotating source addresses.
    # Source+account lockout still applies before hashing, which limits CPU
    # abuse but can affect shared-NAT users; document this residual risk.
    reset_login_throttle(source_key, db)
    reset_login_throttle(account_key, db)

    business = db.query(Business).filter(Business.id == user.business_id).first()

    session_id = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        business_id=user.business_id,
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(user_session)
    db.commit()

    token = create_access_token(
        user_id=user.id,
        business_id=user.business_id,
        role=user.role,
        jti=session_id
    )
    csrf_token = generate_csrf_token()
    set_auth_cookies(response, token, csrf_token)

    return {
        "status": "success",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "business_id": user.business_id,
        },
        "business": {
            "id": business.id if business else user.business_id,
            "name": business.name if business else "OneBoard Business",
            "industry": business.industry if business else "B2B SaaS",
            "current_cash_balance": business.current_cash_balance if business else 0.0
        },
        "token": token,
        "csrf_token": csrf_token
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """Invalidate session in database and clear client cookies."""
    auth_header = request.headers.get("authorization")
    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "oneboard_session" in request.cookies:
        token = request.cookies["oneboard_session"]

    # Logout is a state-changing request. A third-party site must not be
    # able to revoke a founder's cookie-backed session without a CSRF token.
    if not (auth_header and auth_header.lower().startswith("bearer ")):
        verify_csrf_protection(request)

    if token:
        try:
            payload = decode_access_token(token)
        except ValueError:
            # An expired or malformed token cannot identify a live session.
            payload = None
        if payload:
            jti = payload.get("jti")
            if jti:
                session_record = db.query(UserSession).filter(UserSession.id == jti).first()
                # A signed token is not authority to revoke an unrelated session.
                # Check the persisted owner and tenant before changing state.
                if (
                    session_record
                    and session_record.user_id == payload.get("sub")
                    and session_record.business_id == payload.get("biz")
                ):
                    if settings.ONEBOARD_PRODUCTION_MODE and isinstance(db,Session) and db.get_bind().dialect.name=='postgresql':
                        from apps.api.core.database import tenant_lifecycle_lock
                        tenant_lifecycle_lock(db,session_record.business_id,exclusive=True)
                        session_record=db.query(UserSession).filter_by(id=jti,user_id=payload.get('sub'),business_id=payload.get('biz')).populate_existing().first()
                    if session_record is None:
                        clear_auth_cookies(response)
                        return {'status':'success','message':'Logged out successfully.'}
                    session_record.is_revoked = True
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                        # Do not falsely report a successful logout when the
                        # revocation write was not persisted.
                        raise

    clear_auth_cookies(response)
    return {"status": "success", "message": "Logged out successfully."}


@router.get("/me")
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Return authenticated founder details and active business context."""
    business = db.query(Business).filter(Business.id == current_user.business_id).first()
    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "role": current_user.role,
            "business_id": current_user.business_id,
        },
        "business": {
            "id": business.id if business else current_user.business_id,
            "name": business.name if business else "OneBoard Business",
            "industry": business.industry if business else "B2B SaaS",
            "current_cash_balance": business.current_cash_balance if business else 0.0,
            "currency": business.currency if business else "USD"
        }
    }


@router.post("/regenerate-api-key")
def regenerate_api_key_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """Regenerate a new high-entropy API key for the authenticated user."""
    new_key = generate_api_key()
    current_user.api_key = hash_api_key(new_key)
    db.commit()
    return {"api_key": new_key, "message": "API key successfully regenerated."}
