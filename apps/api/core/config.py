from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from pathlib import Path
from typing import Dict, Any

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
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    COOKIE_SECURE: bool = False
    SESSION_EXPIRY_SECONDS: int = 7 * 24 * 3600  # 7 days
    LOGIN_MAX_ATTEMPTS: int = 5
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
