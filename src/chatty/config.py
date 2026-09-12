"""Server-only configuration for the single-laptop demo."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOSITORY = "vaishnavJa/Chatty"


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    backend_model: str = "gpt-5.6-terra"
    repository: str = DEFAULT_REPOSITORY
    port: int = 3000
    web_dir: Path = PROJECT_ROOT / "web"
    request_timeout: float = 45.0
    max_body_bytes: int = 65_536
    session_ttl_seconds: float = 7_200.0
    max_sessions: int = 32
    max_calls_per_session: int = 256
    duplicate_wait_seconds: float = 45.0
    secret_values: tuple[str, ...] = field(default=(), repr=False)

    @classmethod
    def from_env(cls, root: Path = PROJECT_ROOT) -> "Settings":
        # Explicit path: never search parent directories for someone else's .env.
        load_dotenv(root / ".env", override=False)
        os.environ.setdefault("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
        port = int(os.getenv("CHATTY_PORT", "3000"))
        if not 1 <= port <= 65_535:
            raise ValueError("CHATTY_PORT must be between 1 and 65535")
        repository = os.environ["GITHUB_REPOSITORY"].strip()
        if repository != DEFAULT_REPOSITORY:
            raise ValueError("This demo supports only vaishnavJa/Chatty")
        backend = os.getenv("OPENAI_BACKEND_MODEL", "gpt-5.6-terra").strip()
        if not backend:
            raise ValueError("OPENAI_BACKEND_MODEL must not be empty")
        web_dir = Path(os.getenv("CHATTY_WEB_DIR", "web"))
        if not web_dir.is_absolute():
            web_dir = root / web_dir
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            backend_model=backend,
            repository=repository,
            port=port,
            web_dir=web_dir.resolve(),
            secret_values=tuple(
                value
                for key in ("OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")
                if (value := os.getenv(key, "").strip())
            ),
        )

    def redact(self, text: str) -> str:
        for secret in (self.api_key, *self.secret_values):
            if secret:
                text = text.replace(secret, "[redacted]")
        return text
