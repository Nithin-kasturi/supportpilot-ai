from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.2

    policies_dir: Path = PROJECT_ROOT / "data" / "policies"
    chunk_max_chars: int = 800
    chunk_overlap_chars: int = 100

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    retrieval_top_k: int = 3
    retrieval_min_similarity: float = 0.40

    database_path: Path = PROJECT_ROOT / "data" / "sample_data" / "supportpilot.db"

    agent_history_messages: int = 8
    agent_recursion_limit: int = 12
    pending_action_ttl_minutes: int = 10

    # --- Security ---
    app_env: Literal["development", "production"] = "development"
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "supportpilot"
    access_token_minutes: int = 30
    mcp_token_minutes: int = 60
    cookie_name: str = "sp_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = 65_536
    trust_proxy_headers: bool = False
    login_rate_limit_per_ip: int = 10
    login_rate_limit_per_account: int = 5
    chat_rate_limit: int = 30
    sensitive_rate_limit: int = 10
    dev_seed_password: SecretStr | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_serving(self) -> None:
        """Fail closed on insecure configuration. Called by the API and the MCP server at startup."""
        problems: list[str] = []
        secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
        if len(secret) < 32:
            problems.append(
                "JWT_SECRET must be a random value of at least 32 characters "
                '(python -c "import secrets; print(secrets.token_urlsafe(64))").'
            )
        if self.jwt_algorithm != "HS256":
            problems.append("Only HS256 is supported.")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list explicit origins, not '*'.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            problems.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")
        if self.app_env == "production" and not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true when APP_ENV=production.")
        if problems:
            raise RuntimeError("Insecure configuration:\n- " + "\n- ".join(problems))


settings = Settings()