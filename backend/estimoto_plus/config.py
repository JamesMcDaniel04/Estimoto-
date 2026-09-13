from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "production"))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_publishable_key: str = field(default_factory=lambda: os.getenv("SUPABASE_PUBLISHABLE_KEY", ""))
    bridge_url: str = field(default_factory=lambda: os.getenv("BRIDGE_REQUEST_URL", ""))
    estimate_bridge_url: str = field(default_factory=lambda: os.getenv("BRIDGE_ESTIMATE_URL", ""))
    bridge_key: str = field(default_factory=lambda: os.getenv("BRIDGE_KEY", ""))
    dev_sessions_enabled: bool = field(default_factory=lambda: os.getenv("DEV_SESSIONS_ENABLED", "false").lower() == "true")
    dev_token_secret: str = field(default_factory=lambda: os.getenv("DEV_TOKEN_SECRET", ""))
    photo_dir: str = field(default_factory=lambda: os.getenv("PHOTO_DIR", str(Path.home() / ".local/share/estimoto-plus/photos")))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))
    source_sha: str = field(default_factory=lambda: os.getenv("SOURCE_SHA", ""))
    web_dir: str = field(default_factory=lambda: os.getenv("WEB_DIR", ""))
    worker_enabled: bool | None = field(default_factory=lambda: None if os.getenv("WORKER_ENABLED") is None else os.getenv("WORKER_ENABLED", "").lower() == "true")
    worker_interval_seconds: int = field(default_factory=lambda: int(os.getenv("WORKER_INTERVAL_SECONDS", "15")))
