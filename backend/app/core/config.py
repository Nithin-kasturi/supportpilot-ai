from pathlib import Path

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

    # DEVELOPMENT ONLY. Not authentication. Replaced by real auth in Milestone 5.
    demo_customer_email: str = "maya.patel@example.com"

    agent_history_messages: int = 8
    agent_recursion_limit: int = 12
    pending_action_ttl_minutes: int = 10


settings = Settings()