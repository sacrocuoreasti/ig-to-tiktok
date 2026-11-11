import os
import time
import requests
import json
from pathlib import Path
from models import get_setting, log_event
from zernio_client import ZernioClient

class TikTokClient:
    def __init__(self):
        self.mode = get_setting("tiktok_mode", "zernio")
        self.client_key = get_setting("tiktok_client_key", "")
        self.client_secret = get_setting("tiktok_client_secret", "")
        self.access_token = get_setting("tiktok_access_token", "")
        self.session_id = get_setting("tiktok_session_id", "")
        self.base_url = "https://open.tiktokapis.com/v2"

    def is_configured(self):
        """Returns True if test mode is enabled or if valid credentials/cookies/zernio exist."""
        if self.mode == "test_mode":
            return True
        elif self.mode == "zernio":
            zc = ZernioClient()
            return zc.is_configured()
        elif self.mode == "web_session":
            return bool(self.session_id)
        elif self.mode == "official_api":
            return bool(self.access_token)
        return False

    def format_caption(self, original_caption=""):
        """Formats the caption applying prefix, suffix, and TikTok character constraints."""
        include_orig = get_setting("include_original_caption", "true") == "true"
        prefix = get_setting("caption_prefix", "").strip()
        suffix = get_setting("caption_suffix", "").strip()
        clean_mentions = get_setting("clean_ig_mentions", "false") == "true"

        text_parts = []
        if prefix:
            text_parts.append(prefix)

        if include_orig and original_caption:
            caption = original_caption.strip()
            if clean_mentions:
                import re
                caption = re.sub(r'@[A-Za-z0-9_.]+', '', caption)
            text_parts.append(caption)

        if suffix:
            text_parts.append(suffix)

        final_caption = "\n\n".join([p for p in text_parts if p]).strip()
        
        # TikTok title limit is 2200 characters
        if len(final_caption) > 2180:
            final_caption = final_caption[:2180] + "..."

        return final_caption

    def get_creator_info(self):
        """Checks TikTok creator profile & publishing permissions."""
        if self.mode == "test_mode":
            return {
                "success": True,
                "creator_nickname": "Account Test (Simulazione)",
                "creator_avatar_url": "",
                "mode": "test_mode"
            }
        elif self.mode == "zernio":
            zc = ZernioClient()
            if not zc.is_configured():
                return {"success": False, "error": "Zernio API Key mancante nelle impostazioni", "mode": "zernio"}
            res = zc.list_accounts(platform="tiktok")
            if res.get("success"):
                accs = res.get("accounts", [])
                if accs:
                    first = accs[0]
                    uname = first.get("username") or first.get("name") or first.get("_id")
                    return {
                        "success": True,
                        "creator_nickname": f"TikTok via Zernio (@{uname})",
                        "mode": "zernio",
                        "accounts": accs
                    }
                else:
                    return {
                        "success": False,
                        "error": "Nessun account TikTok connesso trovato su Zernio. Collegalo sulla dashboard di Zernio.",
                        "mode": "zernio"
                    }
            return {"success": False, "error": res.get("error"), "mode": "zernio"}

        elif self.mode == "web_session":
            from tiktok_web_uploader import test_tiktok_cookie
            res = test_tiktok_cookie(self.session_id)
            if res.get("valid"):
                return {
                    "success": True,
                    "creator_nickname": "Sessione Web TikTok Connessa",
                    "mode": "web_session",
                    "details": res.get("message")
                }
            else:
                return {
                    "success": False,
                    "error": res.get("message"),
                    "mode": "web_session"
                }

        # OFFICIAL API
        if not self.access_token:
            return {"success": False, "error": "Access Token TikTok non inserito"}

        try:
            url = f"{self.base_url}/post/publish/creator_info/query/"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8"
            }
            resp = requests.post(url, headers=headers, json={}, timeout=10)
            data = resp.json()

            if data.get("error", {}).get("code") != "ok":
                return {
                    "success": False,
                    "error": data.get("error", {}).get("message", "Errore verifica account TikTok")
                }

            creator_data = data.get("data", {})
            return {
                "success": True,
                "creator_nickname": creator_data.get("creator_nickname"),
                "creator_avatar_url": creator_data.get("creator_avatar_url"),
                "privacy_level_options": creator_data.get("privacy_level_options", []),
                "comment_disabled": creator_data.get("comment_disabled", False),
                "duet_disabled": creator_data.get("duet_disabled", False),
                "stitch_disabled": creator_data.get("stitch_disabled", False),
                "max_video_post_duration_sec": creator_data.get("max_video_post_duration_sec", 600),
                "mode": "official_api"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def publish_video(self, video_path, caption="", privacy_level=None):
        """Publishes a video to TikTok using the configured mode."""
        formatted_caption = self.format_caption(caption)
        privacy = privacy_level or get_setting("default_privacy_level", "PUBLIC_TO_EVERYONE")
        post_type = get_setting("tiktok_post_type", "direct")

        # 1. TEST MODE
        if self.mode == "test_mode":
            publish_id = f"test_pub_{int(time.time())}"
            log_event("SUCCESS", f"[TEST MODE] Video {video_path} simulato per TikTok. ID: {publish_id}")
            return {
                "success": True,
                "publish_id": publish_id,
                "status": "PUBLISH_COMPLETE_TEST",
                "mode": "test_mode",
                "caption": formatted_caption
            }

        # 2. ZERNIO UNIFIED API (Recommended: official, fast, zero RAM on host)
        if self.mode == "zernio":
            zc = ZernioClient()
            if not zc.is_configured():
                return {"success": False, "error": "Zernio API Key non configurata nelle impostazioni."}
            return zc.publish_to_tiktok(video_path, caption=formatted_caption)

        # 3. WEB SESSION COOKIE VIA PLAYWRIGHT
        if self.mode == "web_session":
            from tiktok_web_uploader import upload_to_tiktok_via_web
            return upload_to_tiktok_via_web(
                video_path=video_path,
                caption=formatted_caption,
                privacy_level=privacy,
                session_id=self.session_id
            )

        # 4. OFFICIAL TIKTOK API DIRECT POST
        if not self.access_token:
            return {"success": False, "error": "Access Token TikTok mancante. Passa a modalità 'Zernio' o 'Sessione Web Cookie'."}

        if not os.path.exists(video_path):
            return {"success": False, "error": f"File non trovato: {video_path}"}

        file_size = os.path.getsize(video_path)

        try:
            endpoint = "/post/publish/video/init/" if post_type == "direct" else "/post/publish/inbox/video/init/"
            url = f"{self.base_url}{endpoint}"

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8"
            }

            disable_comment = get_setting("tiktok_disable_comments", "false") == "true"
            disable_duet = get_setting("tiktok_disable_duet", "false") == "true"
            disable_stitch = get_setting("tiktok_disable_stitch", "false") == "true"

            post_info = {
                "title": formatted_caption,
                "privacy_level": privacy,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
                "disable_comment": disable_comment,
                "video_cover_timestamp_ms": 1000
            }

            source_info = {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1
            }

            payload = {
                "post_info": post_info,
                "source_info": source_info
            }

            log_event("INFO", f"Inizializzazione caricamento API TikTok per {os.path.basename(video_path)}...")
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            data = resp.json()

            if data.get("error", {}).get("code") != "ok":
                err_msg = data.get("error", {}).get("message", "Errore inizializzazione TikTok")
                log_event("ERROR", f"Errore inizializzazione TikTok: {err_msg}", details=str(data))
                return {"success": False, "error": err_msg, "raw": data}

            publish_id = data.get("data", {}).get("publish_id")
            upload_url = data.get("data", {}).get("upload_url")

            if not upload_url:
                return {"success": False, "error": "TikTok non ha restituito l'upload_url"}

            log_event("INFO", f"Caricamento binario video su TikTok ({file_size // 1024} KB)...")
            with open(video_path, "rb") as vf:
                video_bytes = vf.read()

            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{file_size - 1}/{file_size}"
            }

            upload_resp = requests.put(upload_url, headers=upload_headers, data=video_bytes, timeout=120)
            if upload_resp.status_code not in (200, 201):
                err_msg = f"HTTP {upload_resp.status_code} durante il PUT del video su TikTok"
                log_event("ERROR", err_msg)
                return {"success": False, "error": err_msg}

            log_event("SUCCESS", f"Video pubblicato con successo su TikTok! Publish ID: {publish_id}")
            return {
                "success": True,
                "publish_id": publish_id,
                "status": "PUBLISH_COMPLETE",
                "mode": "official_api",
                "caption": formatted_caption
            }

        except Exception as e:
            log_event("ERROR", f"Eccezione durante la pubblicazione TikTok: {str(e)}")
            return {"success": False, "error": str(e)}
