import os
import re
import time
import base64
import urllib.parse
import subprocess
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import DOWNLOADS_DIR
from models import log_event

def download_reel_with_browser_fallback(permalink, reel_id):
    """
    Downloads an Instagram Reel even when Meta API omits media_url due to copyrighted audio.
    Intercepts the separate video & audio DASH streams from Instagram CDN and merges them with ffmpeg.
    """
    if not permalink:
        return {"success": False, "error": "Permalink Instagram mancante"}

    log_event("INFO", f"Avvio download con fallback browser per il Reel {reel_id} ({permalink})...", reel_id=reel_id)

    video_streams = []
    audio_streams = []

    def on_response(res):
        u = res.url
        if "efg=" in u and ("video" in res.headers.get("content-type", "") or "audio" in res.headers.get("content-type", "")):
            try:
                param = urllib.parse.unquote(u.split("efg=")[1].split("&")[0])
                padded = param + "=" * (-len(param) % 4)
                metadata = base64.b64decode(padded).decode("utf-8", errors="ignore")

                if "audio" in metadata:
                    audio_streams.append({"url": u, "meta": metadata})
                elif "dash_vp9" in metadata or "dash" in metadata:
                    # Parse quality
                    quality = 360
                    if "1440p" in metadata:
                        quality = 1440
                    elif "1080p" in metadata:
                        quality = 1080
                    elif "720p" in metadata:
                        quality = 720
                    elif "540p" in metadata:
                        quality = 540
                    video_streams.append({"url": u, "quality": quality, "meta": metadata})
            except Exception:
                pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page.on("response", on_response)

            page.goto(permalink, timeout=35000, wait_until="domcontentloaded")
            time.sleep(2)

            # Dismiss EU/German/Italian/English cookie consent banners (vital for Render in Germany)
            cookie_buttons = [
                "Alle Cookies erlauben",
                "Optionale Cookies ablehnen",
                "Consenti tutti i cookie",
                "Consenti cookie essenziali e facoltativi",
                "Allow all cookies",
                "Allow essential and optional cookies",
                "Decline optional cookies",
                "Rifiuta cookie facoltativi",
                "Allow",
                "Consenti"
            ]
            for btn_txt in cookie_buttons:
                try:
                    btn = page.locator(f"button:has-text('{btn_txt}')").first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click()
                        time.sleep(1)
                        break
                except Exception:
                    pass

            # Unmute and trigger play to ensure audio track stream is requested
            page.evaluate("""() => {
                const v = document.querySelector('video');
                if (v) {
                    v.muted = false;
                    v.volume = 1;
                    v.play().catch(() => {});
                }
            }""")
            time.sleep(4)
            browser.close()

        if not video_streams:
            return {"success": False, "error": "Nessun flusso video individuato nella pagina Instagram"}

        # Sort video streams by quality descending
        video_streams.sort(key=lambda x: x["quality"], reverse=True)
        chosen_video = video_streams[0]["url"]
        chosen_audio = audio_streams[0]["url"] if audio_streams else None

        # Clean byte ranges to get full media streams
        clean_v_url = re.sub(r"&bytestart=\d+&byteend=\d+", "", chosen_video)
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

        tmp_v = DOWNLOADS_DIR / f"tmp_v_{reel_id}.mp4"
        tmp_a = DOWNLOADS_DIR / f"tmp_a_{reel_id}.m4a"
        dest_path = DOWNLOADS_DIR / f"{reel_id}.mp4"

        # Download video stream
        log_event("INFO", f"Download flusso video ad alta risoluzione per {reel_id}...", reel_id=reel_id)
        rv = requests.get(clean_v_url, headers=headers, stream=True, timeout=40)
        with open(tmp_v, "wb") as f:
            for chunk in rv.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        if chosen_audio:
            clean_a_url = re.sub(r"&bytestart=\d+&byteend=\d+", "", chosen_audio)
            log_event("INFO", f"Download traccia audio stereo AAC per {reel_id}...", reel_id=reel_id)
            ra = requests.get(clean_a_url, headers=headers, stream=True, timeout=30)
            with open(tmp_a, "wb") as f:
                for chunk in ra.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            # Merge with ffmpeg and encode video to H.264 (optimal for TikTok)
            log_event("INFO", f"Unione video e audio con ffmpeg (formato H.264/AAC per TikTok)...", reel_id=reel_id)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_v),
                "-i", str(tmp_a),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac",
                str(dest_path)
            ]
        else:
            # Video only
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_v),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "23",
                str(dest_path)
            ]

        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Cleanup temporary files
        if tmp_v.exists():
            tmp_v.unlink()
        if tmp_a.exists():
            tmp_a.unlink()

        if dest_path.exists() and dest_path.stat().st_size > 1000:
            file_size = dest_path.stat().st_size
            log_event("SUCCESS", f"Reel {reel_id} scaricato e composto con successo tramite browser ({file_size // 1024} KB)!", reel_id=reel_id)
            return {
                "success": True,
                "file_path": str(dest_path),
                "file_size": file_size
            }
        else:
            return {"success": False, "error": "Creazione del file video finale non riuscita"}

    except Exception as e:
        log_event("ERROR", f"Errore fallback download {reel_id}: {str(e)}", reel_id=reel_id)
        return {"success": False, "error": str(e)}

