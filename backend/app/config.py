from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    admin_database_url: str
    readonly_database_url: str
    eval_database_url: str = ""  # eval_readonly role: SELECT on bird_* schemas only

    llm_provider: str = "gemini"  # gemini | anthropic | openai
    llm_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    llm_thinking_budget: int = 0  # Gemini 2.5: 0 = no thinking (plain prompt-to-SQL baseline)
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # local = fastembed/ONNX, no API quota. gemini needs embedding_dim=1536 columns.
    embedding_provider: str = "local"  # local | gemini
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    query_timeout_s: int = 5

    # Product pipeline (the /ask endpoint). Retrieval flags stay off for the 11-table Chinook DB
    # until the ablation shows they help; self-correction is the F4 feature.
    product_schema_retrieval: bool = False
    product_few_shot: bool = False
    self_correction: bool = True
    max_retries: int = 2
    clarification: bool = True  # F9: the model may ask instead of guessing
    feedback_promotes_examples: bool = True  # F10: thumbs-up saves a verified example
    rate_limit_per_hour: int = 20
    cors_origins: str = "http://localhost:3010"
    # How many reverse proxies sit in front of the API and append to X-Forwarded-For (Render/Railway: 1).
    # 0 = ignore the header entirely, so a client cannot spoof its IP to dodge the rate limit.
    trusted_proxy_hops: int = 0


settings = Settings()
