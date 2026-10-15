from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from apps.api.core.database import get_db
from apps.api.core.auth import (
    hash_password, verify_password, create_access_token,
    generate_api_key, get_current_user
)
from apps.api.models.business import User, Business

router = APIRouter(prefix="/api/auth", tags=["Authentication & Multi-Tenant"])

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    company_name: str
    industry: Optional[str] = "B2B SaaS"

@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.strip().lower()).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
        
    token = create_access_token(user_id=user.id, business_id=user.business_id, role=user.role)
    biz = db.query(Business).filter(Business.id == user.business_id).first()
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "business_id": user.business_id,
            "business_name": biz.name if biz else "Unknown"
        }
    }

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")
        
    # Create isolated Business tenant for the new founder
    new_biz = Business(
        name=req.company_name,
        industry=req.industry or "B2B SaaS",
        description=f"Isolated operating environment for {req.company_name}.",
        current_cash_balance=0.0,
        monthly_burn_rate=0.0,
        runway_months=0.0
    )
    db.add(new_biz)
    db.commit()
    db.refresh(new_biz)
    
    api_key = generate_api_key()
    new_user = User(
        email=email,
        name=req.name,
        role="founder",
        hashed_password=hash_password(req.password),
        api_key=api_key,
        business_id=new_biz.id,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    token = create_access_token(user_id=new_user.id, business_id=new_biz.id, role=new_user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "api_key": api_key,
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "name": new_user.name,
            "role": new_user.role,
            "business_id": new_biz.id,
            "business_name": new_biz.name
        }
    }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    biz = db.query(Business).filter(Business.id == current_user.business_id).first()
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "business_id": current_user.business_id,
        "business_name": biz.name if biz else "Default Workspace",
        "api_key_preview": f"{current_user.api_key[:8]}...{current_user.api_key[-4:]}" if current_user.api_key else None
    }

@router.post("/regenerate-api-key")
def regenerate_api_key(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_key = generate_api_key()
    current_user.api_key = new_key
    db.commit()
    return {"status": "success", "api_key": new_key}
