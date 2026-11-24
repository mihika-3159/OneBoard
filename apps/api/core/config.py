from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlsplit

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="allow")

    APP_NAME: str = "OneBoard"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Storage & DB
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/oneboard.db"
    
    # Security & Authentication
    AUTH_SECRET_KEY: str = ""
    ONEBOARD_DEMO_MODE: bool = False
    ONEBOARD_PRODUCTION_MODE: bool = False
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    # Exact public API origin, including optional port. Never trust client
    # X-Forwarded-Host/Proto directly to construct redirects or cookies.
    PUBLIC_API_ORIGIN: str = ""
    COOKIE_SECURE: bool = False
    SESSION_EXPIRY_SECONDS: int = 7 * 24 * 3600  # 7 days
    LOGIN_MAX_ATTEMPTS: int = 5
    # Across different user emails, a single source can otherwise perform
    # unbounded Argon2 verifications despite per-account throttles. Set a
    # separate, higher limit to reduce shared-office/school NAT lockouts.
    LOGIN_SOURCE_MAX_ATTEMPTS: int = 60
    # Registration has its own source-wide budget. A shared office/school NAT
    # should not be restricted to five registrations in five minutes simply
    # because the password-guessing budget is five. Still bounded server-side.
    REGISTRATION_SOURCE_MAX_ATTEMPTS: int = 30
    LOGIN_LOCKOUT_SECONDS: int = 300  # 5 minutes
    
    # Centralized Ollama Model Gateway
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    DEFAULT_MODEL_PROFILE: str = "balanced"  # 'lightweight', 'balanced', 'high_quality'
    
    # Model Profile Presets
    MODEL_PROFILES: Dict[str, Dict[str, str]] = {
        "lightweight": {
            "chat_model": "qwen2.5:1.5b",
            "reasoning_model": "llama3.2:1b",
            "embedding_model": "all-minilm",
            "context_size": "2048",
            "description": "Optimized for standard CPU laptops and lower memory (under 8GB RAM)."
        },
        "balanced": {
            "chat_model": "qwen2.5:7b",
            "reasoning_model": "llama3.1:8b",
            "embedding_model": "nomic-embed-text",
            "context_size": "4096",
            "description": "Recommended for standard 16GB RAM machines. Great balance of speed and depth."
        },
        "high_quality": {
            "chat_model": "qwen2.5:14b",
            "reasoning_model": "llama3.1:8b",
            "embedding_model": "nomic-embed-text",
            "context_size": "8192",
            "description": "For high-performance machines (32GB+ RAM or GPU acceleration)."
        }
    }
    
    # Proactive Background Scheduler
    SCHEDULER_INTERVAL_SECONDS: int = 60

settings = Settings()


def validate_production_configuration(config: Settings) -> None:
    """Reject configurations that would expose multi-tenant data unsafely.

    This is a minimum deployment guard, not a production certification.
    """
    if not config.ONEBOARD_PRODUCTION_MODE:
        return
    errors = []
    if config.ONEBOARD_DEMO_MODE:
        errors.append("ONEBOARD_DEMO_MODE must be disabled")
    if config.DEBUG:
        errors.append("DEBUG must be disabled")
    if not config.COOKIE_SECURE:
        errors.append("COOKIE_SECURE must be enabled behind HTTPS")
    if len(config.AUTH_SECRET_KEY) < 32 or config.AUTH_SECRET_KEY == "oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION":
        errors.append("AUTH_SECRET_KEY must be at least 32 characters and not the demo sentinel")
    if not 60 <= config.SESSION_EXPIRY_SECONDS <= 30 * 24 * 3600:
        errors.append("SESSION_EXPIRY_SECONDS must be between 60 seconds and 30 days")
    if not 1 <= config.LOGIN_MAX_ATTEMPTS <= 20:
        errors.append("LOGIN_MAX_ATTEMPTS must be between 1 and 20")
    if not 20 <= config.LOGIN_SOURCE_MAX_ATTEMPTS <= 200:
        errors.append("LOGIN_SOURCE_MAX_ATTEMPTS must be between 20 and 200")
    if config.LOGIN_SOURCE_MAX_ATTEMPTS <= config.LOGIN_MAX_ATTEMPTS:
        errors.append("LOGIN_SOURCE_MAX_ATTEMPTS must exceed LOGIN_MAX_ATTEMPTS")
    if not 10 <= config.REGISTRATION_SOURCE_MAX_ATTEMPTS <= 100:
        errors.append("REGISTRATION_SOURCE_MAX_ATTEMPTS must be between 10 and 100")
    if config.REGISTRATION_SOURCE_MAX_ATTEMPTS < config.LOGIN_MAX_ATTEMPTS:
        errors.append("REGISTRATION_SOURCE_MAX_ATTEMPTS cannot be lower than LOGIN_MAX_ATTEMPTS")
    if not 10 <= config.LOGIN_LOCKOUT_SECONDS <= 24 * 3600:
        errors.append("LOGIN_LOCKOUT_SECONDS must be between 10 seconds and 24 hours")
    if not config.DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        errors.append("Production multi-tenant mode requires PostgreSQL; SQLite is development-only")
    origins = [origin.strip() for origin in config.CORS_ORIGINS.split(",") if origin.strip()]
    def valid_https_origin(origin: str) -> bool:
        """Allow only a complete HTTPS origin, not an arbitrary URL prefix."""
        try:
            parsed = urlsplit(origin)
            if (parsed.scheme != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path or parsed.query or parsed.fragment
                    or parsed.netloc != parsed.netloc.lower()):
                return False
            parsed.port  # Validate port range and syntax.
            return origin == f"https://{parsed.netloc}"
        except ValueError:
            return False

    if not origins or any(not valid_https_origin(origin) for origin in origins):
        errors.append("CORS_ORIGINS must contain only canonical explicit HTTPS origins")
    if not valid_https_origin(config.PUBLIC_API_ORIGIN):
        errors.append("PUBLIC_API_ORIGIN must be a canonical explicit HTTPS origin")
    if errors:
        raise RuntimeError("Unsafe OneBoard production configuration: " + "; ".join(errors))
