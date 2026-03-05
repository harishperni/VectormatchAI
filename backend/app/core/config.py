from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "ATS Talent Intelligence API"
    app_version: str = "0.1.0"


settings = Settings()
