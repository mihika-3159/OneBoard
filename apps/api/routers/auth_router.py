"""
Authentication router: Founder registration, login, logout, session verification, and API key management.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.core.auth import (
    TOKEN_EXPIRY_SECONDS,
    check_login_throttle,
    clear_auth_cookies,
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_csrf_token,
    get_current_user,
    hash_password,
    record_failed_login,
    reset_login_throttle,
    set_auth_cookies,
    verify_password,
)
from apps.api.core.database import get_db
from apps.api.models.business import Business, BusinessMembership, User, UserSession

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    business_name: Optional[str] = None
    industry: Optional[str] = "B2B SaaS"


class LoginRequest(BaseModel):
    email: str
    password: str


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
    existing_user = db.query(User).filter(User.email == clean_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists."
        )

    biz_name = (req.business_name or f"{req.name}'s Studio").strip()
    business = Business(
        name=biz_name,
        industry=req.industry or "B2B SaaS",
        # Real accounts start without fabricated financial history.
        current_cash_balance=0.0,
        monthly_burn_rate=0.0,
        runway_months=0.0
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    hashed_pw = hash_password(req.password)
    user = User(
        email=clean_email,
        name=req.name.strip(),
        hashed_password=hashed_pw,
        role="founder",
        business_id=business.id,
        api_key=generate_api_key(),
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

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
    db.commit()

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
            "api_key": user.api_key
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
    client_ip = request.client.host if request.client else "unknown"
    throttle_key = f"{client_ip}:{req.email.strip().lower()}"
    check_login_throttle(throttle_key)

    clean_email = req.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if not user or not verify_password(req.password, user.hashed_password):
        record_failed_login(throttle_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated. Please contact support."
        )

    reset_login_throttle(throttle_key)

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
            "api_key": user.api_key
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

    if token:
        try:
            payload = decode_access_token(token)
            jti = payload.get("jti")
            if jti:
                session_record = db.query(UserSession).filter(UserSession.id == jti).first()
                if session_record:
                    session_record.is_revoked = True
                    db.commit()
        except Exception:
            pass

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
            "api_key": current_user.api_key,
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
    current_user.api_key = new_key
    db.commit()
    return {"api_key": new_key, "message": "API key successfully regenerated."}
