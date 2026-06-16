import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str = ""
    TIPZY_API_KEY: str = ""
    TIPZY_BASE_URL: str = "https://tipzysmm.ru/api/v2"
    DATABASE_URL: str = "postgresql+asyncpg://smmbot:CHANGE_ME@127.0.0.1:5432/smmbot_db"
    ADMIN_API_KEY: str = ""
    PLATEGA_WEBHOOK_SECRET: str = ""
    ADMIN_IDS_RAW: str = ""

    @property
    def ADMIN_IDS(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

settings = Settings()
