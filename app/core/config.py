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
    # Photo storage (Cloudinary). Optional on purpose: the test suite
    # replaces the provider at the seam, so the suite must import
    # without real credentials. Uploads fail loudly until they are set.
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()