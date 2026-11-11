import os
import requests
from models import get_setting, set_setting, log_event

class ZernioClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or get_setting("zernio_api_key") or os.environ.get("ZERNIO_API_KEY", "")
        self.base_url = "https://zernio.com/api/v1"

    def is_configured(self):
        return bool(self.api_key and len(self.api_key) > 5)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json"
        }

    def list_accounts(self, platform=None):
        """
        Fetches connected accounts from Zernio.
        Returns: {"success": True/False, "accounts": [...], "error": ...}
        """
        if not self.is_configured():
            return {"success": False, "error": "Zernio API Key non configurata"}

        try:
            params = {}
            if platform:
                params["platform"] = platform

            resp = requests.get(f"{self.base_url}/accounts", headers=self._headers(), params=params, timeout=15)
            data = resp.json()

            if resp.status_code != 200:
                err_msg = data.get("error", data.get("message", f"Errore Zernio HTTP {resp.status_code}"))
                return {"success": False, "error": err_msg}

            # Zernio may return a list directly or a dict with "accounts" or "data"
            accounts = []
            if isinstance(data, list):
                accounts = data
            elif isinstance(data, dict):
                accounts = data.get("accounts") or data.get("data") or []

            return {"success": True, "accounts": accounts}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_tiktok_account_id(self):
        """Finds the first connected TikTok account ID or configured ID."""
        saved_id = get_setting("zernio_tiktok_account_id")
        if saved_id:
            return saved_id

        res = self.list_accounts(platform="tiktok")
        if res.get("success") and res.get("accounts"):
            acc = res["accounts"][0]
            acc_id = acc.get("_id") or acc.get("id") or acc.get("accountId")
            if acc_id:
                set_setting("zernio_tiktok_account_id", acc_id)
                return acc_id
        return None

    def upload_media_file(self, file_path):
        """
        Uploads a local media file to Zernio storage via presigned URL.
        Returns: {"success": True/False, "public_url": ...}
        """
        if not self.is_configured():
            return {"success": False, "error": "Zernio API Key non configurata"}

        if not os.path.exists(file_path):
            return {"success": False, "error": f"File non trovato: {file_path}"}

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        log_event("INFO", f"Richiesta presigned URL Zernio per {filename} ({file_size // 1024} KB)...")

        try:
            # 1. Get Presigned URL
            presign_payload = {
                "filename": filename,
                "contentType": "video/mp4",
                "size": file_size
            }
            presign_res = requests.post(
                f"{self.base_url}/media/presign",
                headers=self._headers(),
                json=presign_payload,
                timeout=15
            )

            if presign_res.status_code not in (200, 201):
                err = presign_res.json().get("error", f"HTTP {presign_res.status_code}")
                return {"success": False, "error": f"Errore presign Zernio: {err}"}

            presign_data = presign_res.json()
            # Handle variations: data may be nested in "data" or top level
            data_obj = presign_data.get("data", presign_data)
            upload_url = data_obj.get("uploadUrl")
            public_url = data_obj.get("publicUrl")

            if not upload_url or not public_url:
                return {"success": False, "error": "Risposta presign incompleta da Zernio"}

            # 2. Upload Binary file to uploadUrl
            log_event("INFO", f"Caricamento video su storage Zernio...")
            with open(file_path, "rb") as f:
                put_headers = {"Content-Type": "video/mp4"}
                put_res = requests.put(upload_url, data=f, headers=put_headers, timeout=120)

            if put_res.status_code not in (200, 201, 204):
                return {"success": False, "error": f"Errore upload binario su Zernio: HTTP {put_res.status_code}"}

            log_event("SUCCESS", f"Video caricato su Zernio con successo!")
            return {"success": True, "public_url": public_url}

        except Exception as e:
            return {"success": False, "error": f"Errore caricamento su Zernio: {str(e)}"}

    def publish_to_tiktok(self, video_path_or_url, caption="", account_id=None, scheduled_for=None):
        """
        Publishes or schedules a video to TikTok using Zernio's API.
        Accepts either a local file path or a public video URL.
        If scheduled_for is provided (ISO 8601 string), the post is scheduled for that date/time.
        """
        if not self.is_configured():
            return {"success": False, "error": "Zernio API Key mancante"}

        target_acc_id = account_id or self.get_tiktok_account_id()
        if not target_acc_id:
            return {
                "success": False,
                "error": "Nessun account TikTok connesso trovato su Zernio. Verifica di aver collegato TikTok nella dashboard di Zernio."
            }

        # Resolve public URL for video
        if video_path_or_url.startswith("http://") or video_path_or_url.startswith("https://"):
            public_url = video_path_or_url
        else:
            # Upload local file
            up_res = self.upload_media_file(video_path_or_url)
            if not up_res.get("success"):
                return {"success": False, "error": up_res.get("error")}
            public_url = up_res.get("public_url")

        action_label = f"programmazione ({scheduled_for})" if scheduled_for else "pubblicazione immediata"
        log_event("INFO", f"Invio richiesta TikTok a Zernio [{action_label}] (Account: {target_acc_id})...")

        privacy = get_setting("tiktok_privacy_level", "PUBLIC_TO_EVERYONE")
        disable_comment = get_setting("tiktok_disable_comments", "false") == "true"
        disable_duet = get_setting("tiktok_disable_duet", "false") == "true"
        disable_stitch = get_setting("tiktok_disable_stitch", "false") == "true"

        try:
            post_payload = {
              "content": caption or "",
              "publishNow": not bool(scheduled_for),
              "mediaItems": [
                  {
                      "type": "video",
                      "url": public_url
                  }
              ],
              "platforms": [
                  {
                      "platform": "tiktok",
                      "accountId": target_acc_id,
                      "platformSpecificData": {
                          "privacyLevel": privacy,
                          "allowComment": not disable_comment,
                          "allowDuet": not disable_duet,
                          "allowStitch": not disable_stitch,
                          "contentPreviewConfirmed": True,
                          "expressConsentGiven": True
                      }
                  }
              ]
            }

            if scheduled_for:
                post_payload["scheduledFor"] = scheduled_for

            resp = requests.post(
                f"{self.base_url}/posts",
                headers=self._headers(),
                json=post_payload,
                timeout=30
            )

            data = resp.json()
            if resp.status_code not in (200, 201):
                err = data.get("error", data.get("message", f"HTTP {resp.status_code}"))
                log_event("ERROR", f"Errore pubblicazione Zernio: {err}", details=str(data))
                return {"success": False, "error": str(err), "raw": data}

            post_obj = data.get("post") or data.get("data") or data
            post_id = post_obj.get("_id") or post_obj.get("id") or f"zernio_{int(time.time())}"

            # Check if specific platform failed or was queued
            tiktok_url = None
            platform_status = "published"
            scheduled_at = None
            warning_msg = None
            platforms_res = post_obj.get("platforms", [])
            for p in platforms_res:
                if p.get("platform") == "tiktok":
                    p_status = p.get("status")
                    if p_status == "failed":
                        fail_reason = p.get("error") or p.get("message") or "Errore pubblicazione TikTok da Zernio"
                        log_event("ERROR", f"Zernio ha segnalato errore su TikTok: {fail_reason}", details=str(p))
                        return {"success": False, "error": fail_reason, "raw": data}
                    elif p_status in ("pending", "scheduled"):
                        platform_status = "scheduled"
                        scheduled_at = p.get("scheduledFor") or post_obj.get("scheduledFor")
                        if p.get("errorMessage"):
                            warning_msg = p.get("errorMessage")
                    tiktok_url = p.get("platformPostUrl")

            if scheduled_for or platform_status == "scheduled":
                log_event("SUCCESS", f"Video programmato per TikTok tramite Zernio! Post ID: {post_id} (Data: {scheduled_at or scheduled_for})")
                return {
                    "success": True,
                    "publish_id": str(post_id),
                    "tiktok_url": tiktok_url,
                    "status": "scheduled",
                    "scheduled_for": scheduled_at or scheduled_for,
                    "warning": warning_msg,
                    "mode": "zernio"
                }

            log_event("SUCCESS", f"Video pubblicato con successo su TikTok tramite Zernio! Post ID: {post_id}")
            return {
                "success": True,
                "publish_id": str(post_id),
                "tiktok_url": tiktok_url,
                "mode": "zernio",
                "status": "PUBLISHED_VIA_ZERNIO"
            }

        except Exception as e:
            log_event("ERROR", f"Eccezione durante pubblicazione Zernio: {str(e)}")
            return {"success": False, "error": str(e)}

    def sync_published_urls(self):
        """
        Polls recent posts from Zernio and updates any database reels that have
        matching tiktok_publish_id with their final resolved platformPostUrl / publishedUrl.
        """
        if not self.is_configured():
            return {"success": False, "error": "Zernio non configurato"}

        try:
            resp = requests.get(f"{self.base_url}/posts", headers=self._headers(), timeout=15)
            if resp.status_code != 200:
                return {"success": False, "error": f"HTTP {resp.status_code}"}

            posts = resp.json().get("posts", [])
            from models import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            updated = 0

            for p in posts:
                p_id = p.get("_id")
                platforms = p.get("platforms", [])
                for pl in platforms:
                    if pl.get("platform") == "tiktok":
                        url = pl.get("platformPostUrl") or pl.get("publishedUrl")
                        if p_id and url:
                            cursor.execute("""
                                UPDATE reels SET
                                    tiktok_url = ?,
                                    status = 'published',
                                    tiktok_status = 'published'
                                WHERE tiktok_publish_id = ? AND (tiktok_url IS NULL OR tiktok_url != ?)
                            """, (url, str(p_id), url))
                            if cursor.rowcount > 0:
                                updated += cursor.rowcount

            conn.commit()
            conn.close()
            return {"success": True, "updated_count": updated}
        except Exception as e:
            return {"success": False, "error": str(e)}
