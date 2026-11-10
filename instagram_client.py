import os
import requests
import json
from pathlib import Path
from config import DOWNLOADS_DIR
from models import get_setting, set_setting, log_event

class InstagramClient:
    def __init__(self, token=None, app_id=None):
        self.token = token or get_setting("instagram_token")
        self.app_id = app_id or get_setting("instagram_id")
        self.base_url = "https://graph.instagram.com"

    def get_account_info(self):
        """Fetches account details (id, username, account_type)."""
        if not self.token:
            return {"success": False, "error": "Token Instagram non configurato"}
        
        try:
            url = f"{self.base_url}/me"
            params = {
                "fields": "id,username,account_type",
                "access_token": self.token
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if "error" in data:
                return {"success": False, "error": data["error"].get("message", "Errore Meta API")}
            
            return {
                "success": True,
                "id": data.get("id"),
                "username": data.get("username"),
                "account_type": data.get("account_type")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def refresh_access_token(self):
        """Refreshes the 60-day long-lived access token."""
        if not self.token:
            return {"success": False, "error": "Nessun token presente"}

        try:
            url = f"{self.base_url}/refresh_access_token"
            params = {
                "grant_type": "ig_refresh_token",
                "access_token": self.token
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if "error" in data:
                return {"success": False, "error": data["error"].get("message")}

            new_token = data.get("access_token")
            expires_in = data.get("expires_in")
            if new_token:
                self.token = new_token
                set_setting("instagram_token", new_token)
                log_event("SUCCESS", f"Token Instagram rinnovato con successo. Scade tra {expires_in // 86400} giorni.")
                return {"success": True, "expires_in": expires_in}
            return {"success": False, "error": "Token non ricevuto"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fetch_recent_reels(self, limit=50):
        """Fetches the latest reels from the connected Instagram account."""
        if not self.token:
            return {"success": False, "error": "Token mancante", "reels": []}

        try:
            url = f"{self.base_url}/me/media"
            params = {
                "fields": "id,caption,media_type,media_product_type,permalink,thumbnail_url,timestamp",
                "access_token": self.token,
                "limit": limit
            }
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()

            if "error" in data:
                err_msg = data["error"].get("message", "Errore Instagram API")
                log_event("ERROR", f"Errore caricamento media Instagram: {err_msg}")
                return {"success": False, "error": err_msg, "reels": []}

            items = data.get("data", [])
            reels = []
            
            for item in items:
                media_type = item.get("media_type")
                product_type = item.get("media_product_type")
                
                # Check if it's a Reel or Video
                if media_type == "VIDEO" or product_type == "REELS":
                    reel_id = item["id"]
                    # Fetch details to see if media_url is provided
                    details = self.get_media_details(reel_id)
                    media_url = details.get("media_url")
                    
                    reel_info = {
                        "id": reel_id,
                        "caption": item.get("caption", ""),
                        "media_type": media_type,
                        "media_product_type": product_type or "REELS",
                        "permalink": item.get("permalink", ""),
                        "thumbnail_url": item.get("thumbnail_url", ""),
                        "media_url": media_url,
                        "timestamp": item.get("timestamp", "")
                    }
                    reels.append(reel_info)

            return {"success": True, "reels": reels}
        except Exception as e:
            log_event("ERROR", f"Eccezione fetch_recent_reels: {str(e)}")
            return {"success": False, "error": str(e), "reels": []}

    def get_media_details(self, media_id):
        """Fetches individual media object, including direct media_url if available."""
        try:
            url = f"{self.base_url}/{media_id}"
            params = {
                "fields": "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp",
                "access_token": self.token
            }
            resp = requests.get(url, params=params, timeout=10)
            return resp.json()
        except Exception:
            return {}

    def download_video(self, media_url, reel_id):
        """Downloads the video MP4 file to local storage."""
        if not media_url:
            return {"success": False, "error": "URL del video assente"}

        try:
            dest_path = DOWNLOADS_DIR / f"{reel_id}.mp4"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            resp = requests.get(media_url, headers=headers, stream=True, timeout=30)
            if resp.status_code != 200:
                return {"success": False, "error": f"HTTP {resp.status_code} durante il download"}

            total_bytes = 0
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)

            if total_bytes < 1000:
                return {"success": False, "error": "File scaricato troppo piccolo o corrotto"}

            return {
                "success": True,
                "file_path": str(dest_path),
                "file_size": total_bytes
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

