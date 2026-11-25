from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from pathlib import Path
from typing import Dict, Any

from apps.api.services.model_identity import valid_digest
from urllib.parse import urlsplit
from ipaddress import ip_address
from sqlalchemy.engine import make_url

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="allow")

    APP_NAME: str = "OneBoard"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Storage & DB
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/oneboard.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT_SECONDS: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    PORTABLE_ARCHIVE_SIGNING_KEY: str = ""
    
    # Security & Authentication
    AUTH_SECRET_KEY: str = ""
    AUTH_PREVIOUS_SECRET_KEY: str = ""
    ACCOUNT_SECURITY_KEY: str = ""
    TENANT_CONTEXT_KEY: str = ""
    AUTH_GLOBAL_ATTEMPTS: int = 600
    ONEBOARD_DEMO_MODE: bool = False
    ONEBOARD_PRODUCTION_MODE: bool = False
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    # Exact public API origin, including optional port. Never trust client
    # X-Forwarded-Host/Proto directly to construct redirects or cookies.
    PUBLIC_API_ORIGIN: str = ""
    # Exact IP addresses of the owner's trusted TLS terminator, never '*'.
    # Only the owner-approved loopback-bound entrypoint consumes this list.
    TRUSTED_PROXY_IPS: str = ""
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
    
    # Separate base64-encoded 32-byte key; never derive from session signing secret.
    PROVIDER_TOKEN_KEY: str = ""
    # Operator-managed configuration, never writable through tenant APIs.
    PROVIDER_ACTIVE_KEY_ID: str = ""
    PROVIDER_ENCRYPTION_KEYS: dict[str, str] = {}
    PROVIDER_CONNECTORS: dict[str, dict[str, Any]] = {}

    # Centralized Ollama Model Gateway
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL_DIGESTS: dict[str, str] = {}
    INFERENCE_MIN_FREE_MIB: int = 512
    INFERENCE_MAX_LOAD_PER_CPU: float = 2.0
    INFERENCE_QUEUE_URL: str = ""
    OLLAMA_LOCAL_REPLICA_PORT: int = 0
    INFERENCE_COMPATIBLE_LOCAL_PORT: int = 0
    INFERENCE_COMPATIBLE_DIGESTS: dict[str, str] = {}
    INFERENCE_REMOTE_ACCELERATOR_MIN_MIB: int = 0
    OLLAMA_CONTEXT_WINDOW: int = 8192
    OLLAMA_MAX_OUTPUT_TOKENS: int = 768
    OLLAMA_MAX_JSON_OUTPUT_TOKENS: int = 1536
    # No remote inference destination is authorized by default.
    OLLAMA_REMOTE_APPROVED: bool = False
    OLLAMA_REMOTE_HOST: str = ""
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
    if any(not name or not valid_digest(digest) for name, digest in config.OLLAMA_MODEL_DIGESTS.items()):
        errors.append("OLLAMA_MODEL_DIGESTS must map model tags to SHA-256 digests")
    if config.OLLAMA_MODEL_DIGESTS:
        profile_models = {
            profile.get(key)
            for profile in config.MODEL_PROFILES.values()
            for key in ("chat_model", "reasoning_model", "embedding_model")
        }
        if not profile_models.issubset(config.OLLAMA_MODEL_DIGESTS):
            errors.append("OLLAMA_MODEL_DIGESTS must pin each configured profile model")
    if config.ONEBOARD_DEMO_MODE:
        errors.append("ONEBOARD_DEMO_MODE must be disabled")
    if config.DEBUG:
        errors.append("DEBUG must be disabled")
    if not 1 <= config.INFERENCE_MIN_FREE_MIB <= 1_048_576 or not 0 < config.INFERENCE_MAX_LOAD_PER_CPU <= 100:
        errors.append("Invalid inference memory or CPU admission limit")
    if not 0 <= config.OLLAMA_LOCAL_REPLICA_PORT <= 65535:
        errors.append("Invalid local inference replica port")
    if not 0 <= config.INFERENCE_COMPATIBLE_LOCAL_PORT <= 65535:
        errors.append("Invalid compatible provider port")
    if config.INFERENCE_COMPATIBLE_LOCAL_PORT and not config.INFERENCE_COMPATIBLE_DIGESTS:
        errors.append("Compatible provider requires explicit model artifact pins")
    if any(not name or not valid_digest(digest) for name, digest in config.INFERENCE_COMPATIBLE_DIGESTS.items()):
        errors.append("Invalid compatible provider model digest")
    if not 0 <= config.INFERENCE_REMOTE_ACCELERATOR_MIN_MIB <= 1_048_576:
        errors.append("Invalid remote accelerator memory limit")
    if not 4096 <= config.OLLAMA_CONTEXT_WINDOW <= 32768:
        errors.append("OLLAMA_CONTEXT_WINDOW must be between 4096 and 32768")
    if config.OLLAMA_CONTEXT_WINDOW <= max(config.OLLAMA_MAX_OUTPUT_TOKENS, config.OLLAMA_MAX_JSON_OUTPUT_TOKENS) + 64:
        errors.append("OLLAMA_CONTEXT_WINDOW must leave room for prompt input")
    if not 64 <= config.OLLAMA_MAX_OUTPUT_TOKENS <= 4096 or not 64 <= config.OLLAMA_MAX_JSON_OUTPUT_TOKENS <= 4096:
        errors.append("Ollama generation token limits must be between 64 and 4096")
    if not 1 <= config.SCHEDULER_INTERVAL_SECONDS <= 3600:
        errors.append("Scheduler interval must be between 1 and 3600 seconds")
    if not config.COOKIE_SECURE:
        errors.append("COOKIE_SECURE must be enabled behind HTTPS")
    if len(config.AUTH_SECRET_KEY) < 32 or config.AUTH_SECRET_KEY == "oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION":
        errors.append("AUTH_SECRET_KEY must be at least 32 characters and not the demo sentinel")
    if not 100 <= config.AUTH_GLOBAL_ATTEMPTS <= 10000:
        errors.append("AUTH_GLOBAL_ATTEMPTS must be between 100 and 10000")
    if config.AUTH_PREVIOUS_SECRET_KEY and (len(config.AUTH_PREVIOUS_SECRET_KEY)<32 or config.AUTH_PREVIOUS_SECRET_KEY=="oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION"):
        errors.append("Previous signing key must be strong")
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
    else:
        # Publicly reachable managed PostgreSQL must authenticate both the
        # TLS channel and server identity. Local disposable/sidecar databases
        # may use private transport, but this does not certify an actual
        # deployment's private network.
        try:
            db_url = make_url(config.DATABASE_URL)
            if db_url.host not in ("localhost", "127.0.0.1", "::1", None):
                if db_url.query.get("sslmode") != "verify-full":
                    errors.append("Remote production PostgreSQL must use sslmode=verify-full")
        except Exception:
            errors.append("Invalid production PostgreSQL DATABASE_URL")
    trusted = [item.strip() for item in config.TRUSTED_PROXY_IPS.split(",") if item.strip()]
    try:
        if not trusted or len(trusted) != len(set(trusted)):
            raise ValueError("Missing or duplicate trusted proxy addresses")
        for item in trusted:
            address = ip_address(item)
            if address.is_unspecified or address.is_multicast:
                raise ValueError("Unsafe trusted proxy address")
            # A literal proxy IP must be selected by the operator. Never
            # accept a CIDR, wildcard, hostname or unbounded trusted network.
    except ValueError:
        errors.append("TRUSTED_PROXY_IPS must list unique explicit IP addresses, never a wildcard or CIDR")
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
    # Remote inference requires a separately approved, exact HTTPS endpoint.
    # Browser downloads and arbitrary URL-based inference are not supported.
    try:
        model_url = urlsplit(config.OLLAMA_BASE_URL)
        model_host = (model_url.hostname or "").lower()
        invalid = (not model_host or bool(model_url.username or model_url.password)
                   or bool(model_url.query or model_url.fragment)
                   or model_url.path not in ("", "/")
                   or model_url.scheme not in ("http", "https"))
        local_model = model_host in ("localhost", "127.0.0.1", "::1")
        if invalid:
            errors.append("OLLAMA_BASE_URL must be a credential-free HTTP(S) origin")
        elif local_model:
            if config.OLLAMA_REMOTE_APPROVED or config.OLLAMA_REMOTE_HOST:
                errors.append("Remote Ollama approval cannot be used for loopback")
        else:
            try:
                ip_address(model_host)
                literal = True
            except ValueError:
                literal = False
            if literal or model_host.endswith((".internal", ".local", ".localhost")) or "." not in model_host:
                errors.append("Remote Ollama requires a non-internal DNS hostname")
            if (model_url.scheme != "https" or not config.OLLAMA_REMOTE_APPROVED
                    or model_host != config.OLLAMA_REMOTE_HOST):
                errors.append("Remote Ollama requires explicit exact-host approval and HTTPS")
    except ValueError:
        errors.append("Invalid OLLAMA_BASE_URL")
    if errors:
        raise RuntimeError("Unsafe OneBoard production configuration: " + "; ".join(errors))
