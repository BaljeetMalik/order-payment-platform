from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",extra="ignore")
    DATABASE_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_ENABLED: bool = True          # tests set this to false
    DEFAULT_CURRENCY: str = "USD"
    SEED_SAMPLE_DATA: bool = True
    RUN_MIGRATIONS: bool = True
    
settings = Settings()