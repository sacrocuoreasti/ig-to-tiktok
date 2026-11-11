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
DEFAULT_ZERNIO_API_KEY = os.environ.get("ZERNIO_API_KEY", "")
DEFAULT_ZERNIO_TIKTOK_ACCOUNT_ID = os.environ.get("ZERNIO_TIKTOK_ACCOUNT_ID", "")
DEFAULT_AUTO_PUBLISH = os.environ.get("AUTO_PUBLISH", "false")
DEFAULT_AUTO_DELETE = os.environ.get("AUTO_DELETE_VIDEO", "true")

def get_disk_usage():
    import shutil
    try:
        total, used, free = shutil.disk_usage(str(BASE_DIR))
        downloads_size = sum(f.stat().st_size for f in DOWNLOADS_DIR.glob("*") if f.is_file())
        return {
            "downloads_size_mb": round(downloads_size / (1024 * 1024), 1),
            "free_disk_mb": round(free / (1024 * 1024), 1),
            "total_disk_mb": round(total / (1024 * 1024), 1),
            "used_disk_mb": round(used / (1024 * 1024), 1)
        }
    except Exception:
        return {"downloads_size_mb": 0, "free_disk_mb": 500, "total_disk_mb": 512, "used_disk_mb": 12}

DEFAULT_SETTINGS = {
    "instagram_id": DEFAULT_INSTAGRAM_ID,
    "instagram_token": DEFAULT_INSTAGRAM_TOKEN,
    "instagram_username": DEFAULT_INSTAGRAM_USERNAME,
    "check_interval_minutes": "10",
    "bot_enabled": "true",
    "tiktok_mode": "zernio",  # zernio (default), web_session, official_api, test_mode
    "zernio_api_key": DEFAULT_ZERNIO_API_KEY,
    "zernio_tiktok_account_id": DEFAULT_ZERNIO_TIKTOK_ACCOUNT_ID,
    "auto_publish": DEFAULT_AUTO_PUBLISH,  # User can toggle this on when ready
    "auto_delete_video": DEFAULT_AUTO_DELETE,  # Auto-cleanup after publish
    "max_disk_cache_mb": "150",
    "gdrive_enabled": "false",
    "gdrive_folder_id": "",
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

