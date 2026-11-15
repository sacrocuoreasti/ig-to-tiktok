import os
import time
import mimetypes
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, Response, session, redirect, url_for
from config import DOWNLOADS_DIR, BASE_DIR
from models import (
    init_db, get_all_settings, set_setting, get_setting,
    get_reels, get_reel, get_stats, get_logs, clear_logs,
    get_admin_credentials, verify_admin_password, update_admin_credentials
)
from instagram_client import InstagramClient
from tiktok_client import TikTokClient
from bot_service import bot, browser_lock

app = Flask(__name__)
app.config["SECRET_KEY"] = "ig-to-tiktok-secret-key-2026"
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # 250 MB max video upload

# Initialize database
init_db()

# Auto-start bot if configured
if get_setting("bot_enabled", "true") == "true":
    bot.start()

@app.before_request
def check_authentication():
    # Public routes that never require authentication
    public_paths = ["/login", "/static", "/api/webhook"]
    for p in public_paths:
        if request.path.startswith(p):
            return None

    # Check if user is logged in
    if not session.get("logged_in"):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "Autenticazione richiesta", "auth_required": True}), 401
        return redirect(url_for("view_login"))

@app.route("/login", methods=["GET", "POST"])
def view_login():
    if session.get("logged_in"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin_user, _ = get_admin_credentials()
        if username == admin_user and verify_admin_password(password):
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("index"))
        else:
            error = "Nome utente o password errati. Riprova."

    return render_template("login.html", error=error)

@app.route("/logout")
def view_logout():
    session.clear()
    return redirect(url_for("view_login"))

@app.route("/api/settings/password", methods=["POST"])
def api_update_password():
    data = request.get_json() or {}
    curr_pwd = data.get("current_password", "")
    new_user = data.get("new_username", "").strip()
    new_pwd = data.get("new_password", "").strip()

    if not verify_admin_password(curr_pwd):
        return jsonify({"success": False, "error": "Password attuale errata"}), 400

    if new_pwd and len(new_pwd) < 4:
        return jsonify({"success": False, "error": "La nuova password deve contenere almeno 4 caratteri"}), 400

    update_admin_credentials(new_username=new_user if new_user else None, new_password=new_pwd if new_pwd else None)
    if new_user:
        session["username"] = new_user

    return jsonify({"success": True, "message": "Credenziali aggiornate con successo!"})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    status = bot.get_status()
    stats = get_stats()
    
    # Account details
    ig = InstagramClient()
    tt = TikTokClient()

    ig_info = {
        "username": get_setting("instagram_username", "sacrocuoreasti"),
        "has_token": bool(ig.token),
        "app_id": get_setting("instagram_id", "")
    }

    tt_info = {
        "is_configured": tt.is_configured(),
        "mode": tt.mode,
        "has_token": bool(tt.access_token)
    }

    from zernio_client import ZernioClient
    zc = ZernioClient()
    zernio_info = {
        "is_configured": zc.is_configured(),
        "has_key": bool(zc.api_key)
    }

    admin_user, _ = get_admin_credentials()

    return jsonify({
        "bot": status,
        "stats": stats,
        "instagram": ig_info,
        "tiktok": tt_info,
        "zernio": zernio_info,
        "admin_username": session.get("username", admin_user)
    })

@app.route("/api/bot/toggle", methods=["POST"])
def api_bot_toggle():
    data = request.get_json() or {}
    enable = data.get("enable")
    
    if enable is None:
        # Toggle
        if bot.running:
            bot.stop()
        else:
            bot.start()
    elif enable:
        bot.start()
    else:
        bot.stop()

    return jsonify({"success": True, "running": bot.running})

@app.route("/api/bot/sync", methods=["POST"])
def api_bot_sync():
    res = bot.run_sync_cycle()
    return jsonify(res)

_last_zernio_sync_time = 0

@app.route("/api/reels")
def api_get_reels():
    global _last_zernio_sync_time
    now = time.time()
    # Auto-sync resolved TikTok URLs from Zernio if not synced in the last 30s
    if now - _last_zernio_sync_time > 30:
        _last_zernio_sync_time = now
        try:
            from zernio_client import ZernioClient
            zc = ZernioClient()
            if zc.is_configured():
                zc.sync_published_urls()
        except Exception:
            pass

    status = request.args.get("status", "all")
    limit = int(request.args.get("limit", 60))
    include_skipped = request.args.get("include_skipped", "false").lower() == "true"
    reels = get_reels(limit=limit, status=status, include_skipped=include_skipped)
    return jsonify({"success": True, "reels": reels})

@app.route("/api/reels/<reel_id>")
def api_get_single_reel(reel_id):
    reel = get_reel(reel_id)
    if not reel:
        return jsonify({"success": False, "error": "Reel non trovato"}), 404
    return jsonify({"success": True, "reel": reel})

@app.route("/api/reels/<reel_id>/download", methods=["POST"])
def api_download_reel(reel_id):
    reel = get_reel(reel_id)
    if not reel:
        return jsonify({"success": False, "error": "Reel non trovato"}), 404

    if reel.get("media_url"):
        ig = InstagramClient()
        res = ig.download_video(reel["media_url"], reel_id)
        from media_validation import validate_video_audio
        if res.get("success") and not validate_video_audio(res.get("file_path"))["success"]:
            res = {"success": False}
    else:
        res = {"success": False}

    if not res.get("success"):
        with browser_lock:
            from instagram_scraper import download_reel_with_browser_fallback
            res = download_reel_with_browser_fallback(reel.get("permalink"), reel_id)

    if res.get("success"):
        from models import update_reel_status
        status = reel.get("status", "")
        if not status.startswith("published") and status not in ("scheduled", "skipped"):
            status = "downloaded"
        update_reel_status(reel_id, status, video_path=res.get("file_path"), error="")
    return jsonify(res)

@app.route("/api/reels/<reel_id>/publish", methods=["POST"])
def api_publish_reel(reel_id):
    data = request.get_json() or {}
    custom_caption = data.get("caption")
    privacy = data.get("privacy_level")
    scheduled_for = data.get("scheduled_for")

    res = bot.publish_single_reel(
        reel_id,
        custom_caption=custom_caption,
        privacy_level=privacy,
        scheduled_for=scheduled_for
    )
    return jsonify(res)

@app.route("/api/reels/<reel_id>/upload", methods=["POST"])
def api_upload_reel_video(reel_id):
    if "video" not in request.files:
        return jsonify({"success": False, "error": "Nessun file inviato"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Nome file non valido"}), 400

    res = bot.handle_uploaded_video(reel_id, file)
    return jsonify(res)

@app.route("/api/reels/<reel_id>/skip", methods=["POST"])
def api_skip_reel(reel_id):
    res = bot.skip_reel(reel_id)
    return jsonify(res)

@app.route("/api/reels/<reel_id>/unskip", methods=["POST"])
def api_unskip_reel(reel_id):
    res = bot.unskip_reel(reel_id)
    return jsonify(res)

@app.route("/api/video/<reel_id>")
def api_stream_video(reel_id):
    video_path = DOWNLOADS_DIR / f"{reel_id}.mp4"
    if not video_path.exists():
        return "Video non trovato", 404
    
    return send_file(
        str(video_path),
        mimetype="video/mp4",
        as_attachment=False,
        conditional=True
    )

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        for k, v in data.items():
            set_setting(k, v)
        return jsonify({"success": True, "message": "Impostazioni salvate con successo"})
    else:
        settings = get_all_settings()
        # Mask sensitive tokens slightly for display if needed
        return jsonify({"success": True, "settings": settings})

@app.route("/api/logs")
def api_logs():
    level = request.args.get("level", "ALL")
    limit = int(request.args.get("limit", 150))
    logs = get_logs(limit=limit, level=level)
    return jsonify({"success": True, "logs": logs})

@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    clear_logs()
    return jsonify({"success": True})

@app.route("/api/test/instagram")
def api_test_instagram():
    ig = InstagramClient()
    res = ig.get_account_info()
    return jsonify(res)

@app.route("/api/zernio/accounts")
def api_zernio_accounts():
    from zernio_client import ZernioClient
    zc = ZernioClient()
    res = zc.list_accounts()
    return jsonify(res)

@app.route("/api/zernio/test", methods=["POST"])
def api_zernio_test():
    data = request.get_json() or {}
    api_key = data.get("api_key")
    from zernio_client import ZernioClient
    zc = ZernioClient(api_key=api_key)
    res = zc.list_accounts()
    if res.get("success"):
        return jsonify({"success": True, "accounts": res.get("accounts", [])})
    else:
        return jsonify({"success": False, "error": res.get("error")})

@app.route("/api/zernio/sync", methods=["GET", "POST"])
def api_zernio_sync():
    """Manual trigger to synchronize post URLs from Zernio to local reels."""
    from zernio_client import ZernioClient
    zc = ZernioClient()
    res = zc.sync_published_urls()
    return jsonify(res)

@app.route("/api/webhook/zernio", methods=["GET", "POST"])
def api_webhook_zernio():
    """Receives async post status updates and resolved TikTok video URLs from Zernio."""
    if request.method == "GET":
        challenge = request.args.get("challenge") or request.args.get("hub.challenge") or "ok"
        return challenge, 200

    data = request.get_json(silent=True) or {}
    event_type = data.get("event") or data.get("type", "unknown")
    from models import log_event, update_reel_tiktok_url_by_post_id

    post_obj = data.get("post") or {}
    post_id = post_obj.get("id") or post_obj.get("_id") or data.get("postId")
    platform_obj = data.get("platform") or {}
    published_url = platform_obj.get("publishedUrl") or platform_obj.get("platformPostUrl")

    if not published_url and "platforms" in post_obj:
        for p in post_obj.get("platforms", []):
            if p.get("platform") == "tiktok":
                published_url = p.get("publishedUrl") or p.get("platformPostUrl")
                break

    if post_id and published_url:
        update_reel_tiktok_url_by_post_id(post_id, published_url, platform_obj.get("platformPostId"))
        log_event("SUCCESS", f"Webhook Zernio: URL TikTok collegato al Reel ({post_id}): {published_url}")
    else:
        log_event("INFO", f"Webhook Zernio ricevuto ({event_type})", details=str(data))

    return jsonify({"received": True, "event": event_type}), 200

@app.route("/api/instagram/refresh", methods=["POST"])
def api_refresh_instagram():
    ig = InstagramClient()
    res = ig.refresh_access_token()
    return jsonify(res)

@app.route("/api/test/tiktok")
def api_test_tiktok():
    tt = TikTokClient()
    res = tt.get_creator_info()
    return jsonify(res)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"[*] Avvio Web Dashboard su http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

