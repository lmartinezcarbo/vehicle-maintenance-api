from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    cors_origins: str = "http://localhost:3000"
    brevo_api_key: str
    email_from: str
    stripe_secret_key: str
    stripe_success_url: str
    stripe_cancel_url: str
    stripe_webhook_secret: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()