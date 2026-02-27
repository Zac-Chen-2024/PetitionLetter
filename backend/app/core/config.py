from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek API (default provider)
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com/v1"

    # OpenAI API (alternative)
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"

    # LLM Provider: "deepseek" (default) or "openai"
    llm_provider: str = "deepseek"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
