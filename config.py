import os
from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DATA_DIR = BASE_DIR / "data"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"

# Load initial values from environment or psw.env
ENV_FILE = BASE_DIR / "psw.env"
env_values = {}
if ENV_FILE.exists():
    env_values = dotenv_values(ENV_FILE)

DEFAULT_INSTAGRAM_ID = os.environ.get("ID") or env_values.get("ID", "")
DEFAULT_INSTAGRAM_TOKEN = os.environ.get("TOKEN") or os.environ.get("token") or env_values.get("token", "")
DEFAULT_INSTAGRAM_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "sacrocuoreasti")
DEFAULT_TIKTOK_SESSION_ID = os.environ.get("TIKTOK_SESSION_ID", "")
DEFAULT_AUTO_PUBLISH = os.environ.get("AUTO_PUBLISH", "false")

DEFAULT_SETTINGS = {
    "instagram_id": DEFAULT_INSTAGRAM_ID,
    "instagram_token": DEFAULT_INSTAGRAM_TOKEN,
    "instagram_username": DEFAULT_INSTAGRAM_USERNAME,
    "check_interval_minutes": "10",
    "bot_enabled": "true",
    "auto_publish": DEFAULT_AUTO_PUBLISH,  # User can toggle this on when ready
    "tiktok_mode": "web_session",  # 'web_session', 'official_api' or 'test_mode'
    "tiktok_session_id": DEFAULT_TIKTOK_SESSION_ID,
    "tiktok_client_key": "",
    "tiktok_client_secret": "",
    "tiktok_access_token": "",
    "tiktok_refresh_token": "",
    "tiktok_post_type": "direct",  # 'direct' or 'inbox' (draft)
    "tiktok_privacy_level": "PUBLIC_TO_EVERYONE",  # 'PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'
    "tiktok_disable_comments": "false",
    "tiktok_disable_duet": "false",
    "tiktok_disable_stitch": "false",
    "caption_prefix": "",
    "caption_suffix": "#reel #chiesa #comunita",
    "include_original_caption": "true",
    "clean_ig_mentions": "false"
}

