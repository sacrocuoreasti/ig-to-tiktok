import os
import re
import time
import base64
import urllib.parse
import subprocess
import requests
import gc
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import DOWNLOADS_DIR
from models import log_event

def download_reel_with_browser_fallback(permalink, reel_id):
    """
    Downloads an Instagram Reel when Meta API omits media_url due to copyrighted audio.
    Intercepts DASH video & audio streams from Instagram CDN and merges them via ffmpeg.
    Designed with strict memory controls for environments with 512MB RAM (Render).
    """
    if not permalink:
        return {"success": False, "error": "Permalink Instagram mancante"}

    log_event("INFO", f"Avvio estrazione flussi video/audio per Reel {reel_id} ({permalink})...", reel_id=reel_id)

    video_streams = []
    audio_streams = []

    def on_response(res):
        u = res.url
        ct = res.headers.get("content-type", "")
        # Look for Facebook/Instagram CDN media streams
        if "efg=" in u or ("fbcdn.net" in u and ("video" in ct or "audio" in ct or ".mp4" in u)):
            try:
                metadata = ""
                if "efg=" in u:
                    param = urllib.parse.unquote(u.split("efg=")[1].split("&")[0])
                    padded = param + "=" * (-len(param) % 4)
                    metadata = base64.b64decode(padded).decode("utf-8", errors="ignore")

                # Detect audio stream
                if "audio" in metadata or "audio" in ct:
                    if not any(a["url"] == u for a in audio_streams):
                        audio_streams.append({"url": u, "meta": metadata})
                # Detect video stream
                elif "dash" in metadata or "video" in ct or ".mp4" in u or "vencode_tag" in metadata:
                    # Estimate quality from bitrate or tag
                    quality = 360
                    if "1080" in metadata or "1080p" in metadata:
                        quality = 1080
                    elif "720" in metadata or "720p" in metadata:
                        quality = 720
                    elif "540" in metadata:
                        quality = 540
                    elif "bitrate" in metadata:
                        # Extract bitrate value if available
                        bm = re.search(r'"bitrate":(\d+)', metadata)
                        if bm:
                            quality = int(bm.group(1))

                    if not any(v["url"] == u for v in video_streams):
                        video_streams.append({"url": u, "quality": quality, "meta": metadata})
            except Exception:
                pass

    gc.collect()

    try:
        with sync_playwright() as p:
            # Ultra low-memory Chromium launch flags for 512MB containers
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    "--no-zygote",
                    "--renderer-process-limit=1",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync",
                    "--js-flags=--max-old-space-size=128"
                ]
            )

            # Use English locale to normalize cookie banners and prompts across all regions
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
            )

            # Pre-inject common Instagram cookies to avoid consent dialogs
            context.add_cookies([
                {"name": "ig_did", "value": "A1B2C3D4-E5F6-7890-ABCD-1234567890AB", "domain": ".instagram.com", "path": "/"},
                {"name": "csrftoken", "value": "1234567890abcdef", "domain": ".instagram.com", "path": "/"},
                {"name": "ig_nrcb", "value": "1", "domain": ".instagram.com", "path": "/"},
                {"name": "datr", "value": "ab12cd34ef56gh78ij90kl12", "domain": ".instagram.com", "path": "/"}
            ])

            page = context.new_page()

            # Abort heavy static assets (images, fonts, stylesheets) to save ~250MB RAM
            def abort_heavy(route):
                rt = route.request.resource_type
                if rt in ["image", "font", "stylesheet"]:
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", abort_heavy)
            page.on("response", on_response)

            try:
                page.goto(permalink, timeout=35000, wait_until="domcontentloaded")
            except Exception as ge:
                log_event("WARNING", f"Navigazione permalink lenta: {str(ge)}", reel_id=reel_id)

            time.sleep(1.5)

            # Dismiss any cookie or consent dialogs that might still appear
            cookie_selectors = [
                "button:has-text('Allow all cookies')",
                "button:has-text('Allow essential and optional cookies')",
                "button:has-text('Allow all')",
                "button:has-text('Accept all')",
                "button:has-text('Alle Cookies erlauben')",
                "button:has-text('Nur erforderliche Cookies erlauben')",
                "button:has-text('Optionale Cookies ablehnen')",
                "button:has-text('Consenti tutti i cookie')",
                "button:has-text('Consenti')",
                "button:has-text('Accept')",
                "div[role='dialog'] button"
            ]
            for sel in cookie_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=2000)
                        time.sleep(0.5)
                        break
                except Exception:
                    pass

            # Unmute and trigger video playback so DASH streaming is requested
            page.evaluate("""() => {
                const videos = document.querySelectorAll('video');
                videos.forEach(v => {
                    v.muted = false;
                    v.volume = 1.0;
                    v.play().catch(() => {});
                });
            }""")

            # Wait briefly for streams to arrive
            for _ in range(8):
                if video_streams and audio_streams:
                    break
                time.sleep(0.5)

            browser.close()

    except Exception as e:
        log_event("ERROR", f"Errore browser Chromium durante fallback per {reel_id}: {str(e)}", reel_id=reel_id)
        gc.collect()
        return {"success": False, "error": f"Errore browser: {str(e)}"}

    gc.collect()

    if not video_streams:
        return {"success": False, "error": "Nessun flusso video individuato nella pagina Instagram"}

    # Sort video streams by quality descending
    video_streams.sort(key=lambda x: x["quality"], reverse=True)
    chosen_video = video_streams[0]["url"]
    chosen_audio = audio_streams[0]["url"] if audio_streams else None

    # Clean byte ranges to fetch complete media files
    clean_v_url = re.sub(r"&bytestart=\d+&byteend=\d+", "", chosen_video)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    tmp_v = DOWNLOADS_DIR / f"tmp_v_{reel_id}.mp4"
    tmp_a = DOWNLOADS_DIR / f"tmp_a_{reel_id}.m4a"
    dest_path = DOWNLOADS_DIR / f"{reel_id}.mp4"

    try:
        # Download video stream
        log_event("INFO", f"Download flusso video per Reel {reel_id}...", reel_id=reel_id)
        rv = requests.get(clean_v_url, headers=headers, stream=True, timeout=40)
        with open(tmp_v, "wb") as f:
            for chunk in rv.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        if chosen_audio:
            clean_a_url = re.sub(r"&bytestart=\d+&byteend=\d+", "", chosen_audio)
            log_event("INFO", f"Download traccia audio AAC per Reel {reel_id}...", reel_id=reel_id)
            ra = requests.get(clean_a_url, headers=headers, stream=True, timeout=30)
            with open(tmp_a, "wb") as f:
                for chunk in ra.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            # Merge with ffmpeg - using single-thread ultrafast to stay within 512MB RAM
            log_event("INFO", f"Composizione video e audio via ffmpeg (H.264/AAC)...", reel_id=reel_id)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_v),
                "-i", str(tmp_a),
                "-threads", "1",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "24",
                "-c:a", "aac",
                str(dest_path)
            ]
        else:
            # Video only
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_v),
                "-threads", "1",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "24",
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
            log_event("SUCCESS", f"Reel {reel_id} pronto ({file_size // 1024} KB)!", reel_id=reel_id)
            return {
                "success": True,
                "file_path": str(dest_path),
                "file_size": file_size
            }
        else:
            return {"success": False, "error": "Creazione del file video finale non riuscita"}

    except Exception as e:
        if tmp_v.exists():
            tmp_v.unlink()
        if tmp_a.exists():
            tmp_a.unlink()
        log_event("ERROR", f"Errore unione flussi per {reel_id}: {str(e)}", reel_id=reel_id)
        return {"success": False, "error": str(e)}
    finally:
        gc.collect()
