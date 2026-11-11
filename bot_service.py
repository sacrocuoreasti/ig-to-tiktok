import os
import time
import gc
import threading
from datetime import datetime, timedelta
from pathlib import Path
from instagram_client import InstagramClient
from tiktok_client import TikTokClient
from models import (
    get_setting, set_setting, save_or_update_reel,
    update_reel_status, get_reel, log_event
)
from config import DOWNLOADS_DIR

# Global lock to ensure at most one Playwright browser runs at a time (essential for 512MB RAM)
browser_lock = threading.Lock()

class BotService:
    def __init__(self):
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.last_check_time = None
        self.next_check_time = None
        self.is_checking = False

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            set_setting("bot_enabled", "true")
            self.thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.thread.start()
            log_event("INFO", "Bot di monitoraggio avviato.")

    def stop(self):
        with self.lock:
            self.running = False
            set_setting("bot_enabled", "false")
            log_event("INFO", "Bot di monitoraggio messo in pausa.")

    def get_status(self):
        return {
            "running": self.running,
            "is_checking": self.is_checking,
            "last_check": self.last_check_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_check_time else None,
            "next_check": self.next_check_time.strftime("%Y-%m-%d %H:%M:%S") if self.next_check_time else None,
            "auto_publish": get_setting("auto_publish", "false") == "true",
            "interval_minutes": int(get_setting("check_interval_minutes", "10")),
            "tiktok_mode": get_setting("tiktok_mode", "zernio")
        }

    def _worker_loop(self):
        # Initial check delayed to allow web server to boot smoothly
        time.sleep(5)
        while self.running:
            try:
                self.run_sync_cycle()
            except Exception as e:
                log_event("ERROR", f"Errore nel ciclo del bot: {str(e)}")

            # Calculate sleep interval
            try:
                interval_min = max(2, int(get_setting("check_interval_minutes", "10")))
            except Exception:
                interval_min = 10

            self.next_check_time = datetime.now() + timedelta(minutes=interval_min)

            # Sleep in 1-second chunks so we can stop promptly
            for _ in range(interval_min * 60):
                if not self.running:
                    break
                time.sleep(1)

    def run_sync_cycle(self):
        """
        Executes a single check cycle against Instagram.
        Safeguarded against RAM overflow: never spawns multiple browsers in tight loops.
        """
        if self.is_checking:
            return {"success": False, "message": "Controllo già in corso"}

        self.is_checking = True
        self.last_check_time = datetime.now()

        try:
            log_event("INFO", "Controllo nuovi Reel su Instagram in corso...")
            ig = InstagramClient()
            res = ig.fetch_recent_reels(limit=50)

            if not res.get("success"):
                log_event("ERROR", f"Impossibile verificare Instagram: {res.get('error')}")
                return {"success": False, "error": res.get("error")}

            reels = res.get("reels", [])
            new_count = 0
            downloaded_count = 0
            published_count = 0

            auto_publish = get_setting("auto_publish", "false") == "true"
            tt = TikTokClient()

            for r in reels:
                is_new, current_status = save_or_update_reel(r)
                reel_id = r["id"]

                # If the reel is new or pending
                if is_new or current_status == "new":
                    new_count += 1
                    media_url = r.get("media_url")

                    if media_url:
                        # Direct download available via Meta API (lightweight, no browser needed)
                        log_event("INFO", f"Nuovo Reel trovato: {reel_id}. Download via Meta API...", reel_id=reel_id)
                        dl_res = ig.download_video(media_url, reel_id)
                        if dl_res.get("success"):
                            video_path = dl_res.get("file_path")
                            update_reel_status(reel_id, "downloaded", video_path=video_path)
                            downloaded_count += 1
                            log_event("SUCCESS", f"Reel {reel_id} scaricato e pronto ({dl_res.get('file_size') // 1024} KB)", reel_id=reel_id)

                            # Auto-publish if enabled
                            if auto_publish:
                                log_event("INFO", f"Auto-pubblicazione attiva: invio a TikTok di {reel_id}...", reel_id=reel_id)
                                with browser_lock:
                                    pub_res = tt.publish_video(video_path, caption=r.get("caption", ""))
                                if pub_res.get("success"):
                                    pub_status = "published_test" if pub_res.get("mode") == "test_mode" else "published"
                                    update_reel_status(
                                        reel_id,
                                        pub_status,
                                        tiktok_id=pub_res.get("publish_id"),
                                        tiktok_status=pub_res.get("status")
                                    )
                                    published_count += 1
                                    log_event("SUCCESS", f"Reel {reel_id} pubblicato con successo su TikTok!", reel_id=reel_id)

                                    if get_setting("auto_delete_video", "true") == "true":
                                        self._cleanup_single_file(video_path, reel_id)
                                else:
                                    update_reel_status(reel_id, "error", error=pub_res.get("error"))
                                    log_event("ERROR", f"Errore pubblicazione TikTok per {reel_id}: {pub_res.get('error')}", reel_id=reel_id)
                        else:
                            update_reel_status(reel_id, "error", error=dl_res.get("error"))
                    else:
                        # Meta omits media_url due to copyrighted audio
                        # Mark as audio_restricted - DO NOT launch browser loop here to prevent Render OOM crash!
                        update_reel_status(reel_id, "audio_restricted")
                        log_event(
                            "INFO",
                            f"Reel {reel_id} ha audio con copyright (nessun URL diretto da Meta). Pronto per pubblicazione manuale o fallback singolo.",
                            reel_id=reel_id
                        )

            # If auto-publish is ON, process at most ONE audio-restricted reel per check cycle to keep RAM under 512MB
            if auto_publish and published_count == 0:
                for r in reels:
                    reel_id = r["id"]
                    curr = get_reel(reel_id)
                    if curr and curr.get("status") == "audio_restricted" and not curr.get("tiktok_id"):
                        log_event("INFO", f"Auto-pubblicazione singolo Reel con audio copyright: {reel_id}...", reel_id=reel_id)
                        self.publish_single_reel(reel_id)
                        break

            summary = f"Controllo completato: {len(reels)} reel esaminati ({new_count} nuovi, {downloaded_count} scaricati, {published_count} pubblicati)."
            log_event("INFO", summary)
            return {
                "success": True,
                "reels_checked": len(reels),
                "new_count": new_count,
                "downloaded_count": downloaded_count,
                "published_count": published_count
            }

        except Exception as e:
            log_event("ERROR", f"Errore non gestito durante sync_cycle: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            self.is_checking = False
            gc.collect()

    def publish_single_reel(self, reel_id, custom_caption=None, privacy_level=None):
        """
        Manually publishes or re-publishes a specific reel to TikTok.
        Protected with browser_lock to prevent simultaneous browser instances.
        """
        reel = get_reel(reel_id)
        if not reel:
            return {"success": False, "error": "Reel non trovato nel database"}

        video_path = reel.get("video_path")

        # If video_path is missing or file does not exist, prepare it
        if not video_path or not os.path.exists(video_path):
            expected_path = DOWNLOADS_DIR / f"{reel_id}.mp4"
            if expected_path.exists() and expected_path.stat().st_size > 1000:
                video_path = str(expected_path)
            elif reel.get("media_url"):
                ig = InstagramClient()
                dl = ig.download_video(reel["media_url"], reel_id)
                if dl.get("success"):
                    video_path = dl["file_path"]
                    update_reel_status(reel_id, "downloaded", video_path=video_path)
                else:
                    return {"success": False, "error": f"Impossibile scaricare il video: {dl.get('error')}"}
            elif reel.get("permalink"):
                # Use browser fallback under global lock
                with browser_lock:
                    from instagram_scraper import download_reel_with_browser_fallback
                    dl = download_reel_with_browser_fallback(reel["permalink"], reel_id)
                if dl.get("success"):
                    video_path = dl["file_path"]
                    update_reel_status(reel_id, "downloaded", video_path=video_path)
                else:
                    return {"success": False, "error": f"Impossibile estrarre il video: {dl.get('error')}"}
            else:
                return {
                    "success": False,
                    "error": "File video mancante e permalink non disponibile."
                }

        caption_to_use = custom_caption if custom_caption is not None else reel.get("caption", "")

        tt = TikTokClient()
        log_event("INFO", f"Pubblicazione del Reel {reel_id} su TikTok...", reel_id=reel_id)

        with browser_lock:
            pub_res = tt.publish_video(video_path, caption=caption_to_use, privacy_level=privacy_level)

        if pub_res.get("success"):
            pub_status = "published_test" if pub_res.get("mode") == "test_mode" else "published"
            update_reel_status(
                reel_id,
                pub_status,
                video_path=video_path,
                tiktok_id=pub_res.get("publish_id"),
                tiktok_status=pub_res.get("status")
            )
            log_event("SUCCESS", f"Reel {reel_id} pubblicato con successo su TikTok!", reel_id=reel_id)

            # Auto-delete video from disk if enabled to save Render disk space
            if get_setting("auto_delete_video", "true") == "true":
                self._cleanup_single_file(video_path, reel_id)

            gc.collect()
            return {"success": True, "publish_id": pub_res.get("publish_id"), "mode": pub_res.get("mode")}
        else:
            update_reel_status(reel_id, "error", error=pub_res.get("error"))
            log_event("ERROR", f"Errore pubblicazione manuale {reel_id}: {pub_res.get('error')}", reel_id=reel_id)
            gc.collect()
            return {"success": False, "error": pub_res.get("error")}

    def handle_uploaded_video(self, reel_id, file_storage):
        """Saves a manually uploaded MP4 for a reel (e.g. for audio-restricted reels)."""
        reel = get_reel(reel_id)
        if not reel:
            return {"success": False, "error": "Reel non trovato"}

        dest_path = DOWNLOADS_DIR / f"{reel_id}.mp4"
        file_storage.save(str(dest_path))

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            update_reel_status(reel_id, "downloaded", video_path=str(dest_path), error="")
            log_event("SUCCESS", f"File video MP4 caricato manualmente per il Reel {reel_id}.", reel_id=reel_id)
            return {"success": True, "file_path": str(dest_path)}
        else:
            return {"success": False, "error": "File caricato non valido o vuoto"}

    def _cleanup_single_file(self, video_path, reel_id):
        """Safely removes a published video from disk to keep storage usage low."""
        if not video_path:
            return
        try:
            p = Path(video_path)
            if p.exists():
                p.unlink()
                log_event("INFO", f"Spazio disco liberato: eliminato {p.name}", reel_id=reel_id)
        except Exception as e:
            log_event("WARNING", f"Impossibile rimuovere {video_path}: {str(e)}", reel_id=reel_id)

    def skip_reel(self, reel_id):
        """Marks a reel as skipped so it won't be auto-published."""
        update_reel_status(reel_id, "skipped")
        log_event("INFO", f"Reel {reel_id} contrassegnato come ignorato.", reel_id=reel_id)
        return {"success": True}

# Singleton instance
bot = BotService()
