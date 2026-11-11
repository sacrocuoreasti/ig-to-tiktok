import sqlite3
import json
from datetime import datetime
from config import DB_PATH, DEFAULT_SETTINGS

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
        error_message TEXT,
        discovered_at TEXT,
        published_at TEXT
    )
    """)

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
    return {row["key"]: row["value"] for row in rows}

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

    cursor.execute("SELECT id, status, video_path FROM reels WHERE id = ?", (reel_data["id"],))
    existing = cursor.fetchone()

    if existing:
        # Update existing reel fields if needed without overwriting already downloaded/published status
        cursor.execute("""
            UPDATE reels SET
                caption = coalesce(?, caption),
                permalink = coalesce(?, permalink),
                thumbnail_url = coalesce(?, thumbnail_url),
                media_url = coalesce(?, media_url),
                has_media_url = coalesce(?, has_media_url)
            WHERE id = ?
        """, (
            reel_data.get("caption"),
            reel_data.get("permalink"),
            reel_data.get("thumbnail_url"),
            reel_data.get("media_url"),
            1 if reel_data.get("media_url") else 0,
            reel_data["id"]
        ))
        conn.commit()
        conn.close()
        return False, existing["status"]  # is_new = False
    else:
        cursor.execute("""
            INSERT INTO reels (
                id, caption, media_type, media_product_type, permalink,
                thumbnail_url, media_url, has_media_url, video_path,
                timestamp, status, discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reel_data["id"],
            reel_data.get("caption", ""),
            reel_data.get("media_type", "VIDEO"),
            reel_data.get("media_product_type", "REELS"),
            reel_data.get("permalink", ""),
            reel_data.get("thumbnail_url", ""),
            reel_data.get("media_url", ""),
            1 if reel_data.get("media_url") else 0,
            reel_data.get("video_path"),
            reel_data.get("timestamp", ""),
            reel_data.get("status", "new"),
            now_iso
        ))
        conn.commit()
        conn.close()
        return True, reel_data.get("status", "new")  # is_new = True

def update_reel_status(reel_id, status, video_path=None, tiktok_id=None, tiktok_status=None, error=None):
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

def get_reel(reel_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reels WHERE id = ?", (reel_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_reels(limit=50, status=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status and status != "all":
        cursor.execute("SELECT * FROM reels WHERE status = ? ORDER BY timestamp DESC LIMIT ?", (status, limit))
    else:
        cursor.execute("SELECT * FROM reels ORDER BY timestamp DESC LIMIT ?", (limit,))
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

    conn.close()
    return {
        "total_reels": total_reels,
        "published": published,
        "pending": pending,
        "errors": errors,
        "restricted": restricted
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

