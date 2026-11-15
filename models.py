import sqlite3
import json
from datetime import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from config import DB_PATH, DEFAULT_SETTINGS

SKIPPED_REELS_FILE = Path(__file__).resolve().parent / "skipped_reels.json"

def get_skipped_reel_ids():
    if SKIPPED_REELS_FILE.exists():
        try:
            with open(SKIPPED_REELS_FILE, "r") as f:
                data = json.load(f)
                return set(str(x) for x in data)
        except Exception:
            return set()
    return set()

def add_skipped_reel_id(reel_id):
    skipped = get_skipped_reel_ids()
    skipped.add(str(reel_id))
    try:
        with open(SKIPPED_REELS_FILE, "w") as f:
            json.dump(sorted(list(skipped)), f, indent=2)
    except Exception:
        pass

def remove_skipped_reel_id(reel_id):
    skipped = get_skipped_reel_ids()
    skipped.discard(str(reel_id))
    try:
        with open(SKIPPED_REELS_FILE, "w") as f:
            json.dump(sorted(list(skipped)), f, indent=2)
    except Exception:
        pass

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

ENV_FALLBACKS = {
    "instagram_token": ["TOKEN", "token", "INSTAGRAM_TOKEN", "IG_TOKEN"],
    "instagram_id": ["ID", "id", "INSTAGRAM_ID", "IG_ID"],
    "instagram_username": ["INSTAGRAM_USERNAME"],
    "tiktok_session_id": ["TIKTOK_SESSION_ID", "tiktok_session_id", "SESSION_ID", "sessionid"],
    "tiktok_mode": ["TIKTOK_MODE"],
    "zernio_api_key": ["ZERNIO_API_KEY", "zernio_api_key", "ZERNIO_KEY"],
    "zernio_tiktok_account_id": ["ZERNIO_TIKTOK_ACCOUNT_ID", "zernio_tiktok_account_id"],
    "tiktok_access_token": ["TIKTOK_ACCESS_TOKEN"],
    "tiktok_client_key": ["TIKTOK_CLIENT_KEY"],
    "tiktok_client_secret": ["TIKTOK_CLIENT_SECRET"],
    "auto_publish": ["AUTO_PUBLISH"],
    "check_interval_minutes": ["CHECK_INTERVAL_MINUTES"]
}

def get_env_fallback(key):
    import os
    for env_k in ENV_FALLBACKS.get(key, []):
        val = os.environ.get(env_k)
        if val and val.strip():
            return val.strip()
    return None

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table for settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Table for reels
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reels (
        id TEXT PRIMARY KEY,
        caption TEXT,
        media_type TEXT,
        media_product_type TEXT,
        permalink TEXT,
        thumbnail_url TEXT,
        media_url TEXT,
        has_media_url INTEGER DEFAULT 0,
        video_path TEXT,
        timestamp TEXT,
        status TEXT DEFAULT 'new',
        tiktok_publish_id TEXT,
        tiktok_status TEXT,
        tiktok_url TEXT,
        error_message TEXT,
        discovered_at TEXT,
        published_at TEXT
    )
    """)

    # Migration: Ensure tiktok_url exists in existing reels table
    cursor.execute("PRAGMA table_info(reels)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "tiktok_url" not in columns:
        cursor.execute("ALTER TABLE reels ADD COLUMN tiktok_url TEXT")
    if "scheduled_for" not in columns:
        cursor.execute("ALTER TABLE reels ADD COLUMN scheduled_for TEXT")

    # Table for logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        level TEXT,
        message TEXT,
        details TEXT,
        reel_id TEXT
    )
    """)

    conn.commit()

    # Seed default settings if not exists or if currently empty but env exists
    for key, value in DEFAULT_SETTINGS.items():
        env_val = get_env_fallback(key)
        effective_val = env_val if env_val else value

        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(effective_val)))
        elif (not row["value"] or row["value"] == "None" or not str(row["value"]).strip()) and effective_val:
            cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (str(effective_val), key))

    # Ensure default tiktok_mode is zernio if not set in env
    if not get_env_fallback("tiktok_mode"):
        cursor.execute("UPDATE settings SET value = 'zernio' WHERE key = 'tiktok_mode'")

    # Ensure default auto_publish is true
    if not get_env_fallback("auto_publish"):
        cursor.execute("UPDATE settings SET value = 'true' WHERE key = 'auto_publish'")

    conn.commit()
    conn.close()

def get_setting(key, default=None):
    # Check environment variable first (crucial for Render and Docker)
    env_val = get_env_fallback(key)
    if env_val:
        return env_val

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row is not None and row["value"] and str(row["value"]).strip():
        return row["value"]
    return default

def get_all_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    settings = {row["key"]: row["value"] for row in rows}
    
    # Priority to environment variables (e.g. on Render)
    for k in ENV_FALLBACKS:
        env_val = get_env_fallback(k)
        if env_val:
            settings[k] = env_val

    # Ensure tiktok_mode defaults to zernio
    if not settings.get("tiktok_mode"):
        settings["tiktok_mode"] = "zernio"

    return settings

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    conn.commit()
    conn.close()

def save_or_update_reel(reel_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.utcnow().isoformat()
    reel_id_str = str(reel_data["id"])

    cursor.execute("SELECT id, status, video_path FROM reels WHERE id = ?", (reel_id_str,))
    existing = cursor.fetchone()

    skipped_ids = get_skipped_reel_ids()
    is_permanently_skipped = reel_id_str in skipped_ids

    if existing:
        target_status = "skipped" if (is_permanently_skipped or existing["status"] == "skipped") else existing["status"]
        cursor.execute("""
            UPDATE reels SET
                caption = coalesce(?, caption),
                permalink = coalesce(?, permalink),
                thumbnail_url = coalesce(?, thumbnail_url),
                media_url = coalesce(?, media_url),
                has_media_url = coalesce(?, has_media_url),
                status = ?
            WHERE id = ?
        """, (
            reel_data.get("caption"),
            reel_data.get("permalink"),
            reel_data.get("thumbnail_url"),
            reel_data.get("media_url"),
            1 if reel_data.get("media_url") else 0,
            target_status,
            reel_id_str
        ))
        conn.commit()
        conn.close()
        return False, target_status  # is_new = False
    else:
        initial_status = "skipped" if is_permanently_skipped else reel_data.get("status", "new")
        cursor.execute("""
            INSERT INTO reels (
                id, caption, media_type, media_product_type, permalink,
                thumbnail_url, media_url, has_media_url, video_path,
                timestamp, status, discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reel_id_str,
            reel_data.get("caption", ""),
            reel_data.get("media_type", "VIDEO"),
            reel_data.get("media_product_type", "REELS"),
            reel_data.get("permalink", ""),
            reel_data.get("thumbnail_url", ""),
            reel_data.get("media_url", ""),
            1 if reel_data.get("media_url") else 0,
            reel_data.get("video_path"),
            reel_data.get("timestamp", ""),
            initial_status,
            now_iso
        ))
        conn.commit()
        conn.close()
        # If it was in skipped_reels.json, never treat it as new for auto-publishing
        return (not is_permanently_skipped), initial_status

def update_reel_status(reel_id, status, video_path=None, tiktok_id=None, tiktok_status=None, error=None, tiktok_url=None, scheduled_for=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.utcnow().isoformat()

    updates = ["status = ?"]
    params = [status]

    if video_path is not None:
        updates.append("video_path = ?")
        params.append(video_path)

    if tiktok_id is not None:
        updates.append("tiktok_publish_id = ?")
        params.append(tiktok_id)

    if tiktok_status is not None:
        updates.append("tiktok_status = ?")
        params.append(tiktok_status)

    if tiktok_url is not None:
        updates.append("tiktok_url = ?")
        params.append(tiktok_url)

    if scheduled_for is not None:
        updates.append("scheduled_for = ?")
        params.append(scheduled_for)

    if error is not None:
        updates.append("error_message = ?")
        params.append(error)

    if status in ("published", "published_test"):
        updates.append("published_at = ?")
        params.append(now_iso)

    params.append(reel_id)
    cursor.execute(f"UPDATE reels SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

def update_reel_tiktok_url_by_post_id(post_id, tiktok_url, platform_post_id=None):
    """Updates tiktok_url and optionally tiktok_status/status when Zernio resolves the URL."""
    if not post_id or not tiktok_url:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reels SET
            tiktok_url = ?,
            tiktok_status = 'published'
        WHERE tiktok_publish_id = ?
    """, (tiktok_url, str(post_id)))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_reel(reel_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reels WHERE id = ?", (reel_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_reels(limit=50, status=None, include_skipped=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status and status != "all":
        cursor.execute("SELECT * FROM reels WHERE status = ? ORDER BY timestamp DESC LIMIT ?", (status, limit))
    else:
        if include_skipped:
            cursor.execute("SELECT * FROM reels ORDER BY timestamp DESC LIMIT ?", (limit,))
        else:
            cursor.execute("SELECT * FROM reels WHERE status != 'skipped' ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM reels")
    total_reels = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE status IN ('published', 'published_test')")
    published = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE status IN ('new', 'downloaded')")
    pending = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE status = 'error'")
    errors = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE status = 'audio_restricted'")
    restricted = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE status = 'skipped'")
    skipped = cursor.fetchone()[0]

    conn.close()
    return {
        "total_reels": total_reels,
        "published": published,
        "pending": pending,
        "errors": errors,
        "restricted": restricted,
        "skipped": skipped
    }

def log_event(level, message, details=None, reel_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO logs (timestamp, level, message, details, reel_id)
        VALUES (?, ?, ?, ?, ?)
    """, (now_iso, level.upper(), message, details, reel_id))

    # Keep only the latest 1000 logs
    cursor.execute("""
        DELETE FROM logs WHERE id NOT IN (
            SELECT id FROM logs ORDER BY id DESC LIMIT 1000
        )
    """)

    conn.commit()
    conn.close()

def get_logs(limit=100, level=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if level and level != "ALL":
        cursor.execute("SELECT * FROM logs WHERE level = ? ORDER BY id DESC LIMIT ?", (level.upper(), limit))
    else:
        cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM logs")
    conn.commit()
    conn.close()

def get_admin_credentials():
    username = get_setting("admin_username", "admin")
    password_hash = get_setting("admin_password_hash", None)
    if not password_hash:
        password_hash = generate_password_hash("admin", method="pbkdf2:sha256")
        set_setting("admin_password_hash", password_hash)
        set_setting("admin_username", "admin")
    return username, password_hash

def verify_admin_password(password):
    _, pwd_hash = get_admin_credentials()
    return check_password_hash(pwd_hash, password)

def update_admin_credentials(new_username=None, new_password=None):
    if new_username and new_username.strip():
        set_setting("admin_username", new_username.strip())
    if new_password and new_password.strip():
        pwd_hash = generate_password_hash(new_password.strip(), method="pbkdf2:sha256")
        set_setting("admin_password_hash", pwd_hash)
    return True

