import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

# Railway'da konteyner diski har deploy'da tozalanadi, fayllar Volume'da turishi kerak
DATA_DIR = Path(os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or BASE_DIR)
MEDIA_DIR = DATA_DIR / "media"
DOCS_DIR = DATA_DIR / "hujjatlar"


@dataclass(frozen=True)
class Config:
    telegram_token: str
    owner_id: int | None
    gemini_api_key: str
    gemini_model: str
    timezone: ZoneInfo
    database_url: str


def load_config() -> Config:
    missing = [
        name
        for name in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "DATABASE_URL")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise SystemExit(f".env faylida to'ldirilmagan: {', '.join(missing)}")

    owner = os.getenv("OWNER_TELEGRAM_ID", "").strip()
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"].strip(),
        owner_id=int(owner) if owner else None,
        gemini_api_key=os.environ["GEMINI_API_KEY"].strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip(),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent").strip()),
        database_url=os.environ["DATABASE_URL"].strip(),
    )
