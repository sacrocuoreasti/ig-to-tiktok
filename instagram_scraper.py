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
from media_validation import validate_video_audio

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
        # Look for Facebook/Instagram CDN media streams (fbcdn.net, cdninstagram.com, instagram.com)
        if any(d in u for d in ["fbcdn.net", "cdninstagram.com", "instagram.com"]) and (
            "video" in ct or "audio" in ct or ".mp4" in u or "efg=" in u or "bytestart=" in u or ".m4a" in u
        ):
            try:
                metadata = ""
                if "efg=" in u:
                    param = urllib.parse.unquote(u.split("efg=")[1].split("&")[0])
                    padded = param + "=" * (-len(param) % 4)
                    metadata = base64.b64decode(padded).decode("utf-8", errors="ignore")

                # Detect audio stream
                if "_audio" in metadata or "heaac" in metadata or "audio/" in ct or ".m4a" in u:
                    if not any(a["url"] == u for a in audio_streams):
                        audio_streams.append({"url": u, "meta": metadata})
                # Detect video stream
                elif "video" in ct or "dash" in metadata or "baseline" in metadata or ".mp4" in u or "vencode_tag" in metadata:
                    # Estimate quality from bitrate or tag
                    quality = 360
                    if "1080" in metadata or "1080p" in metadata:
                        quality = 1080
                    elif "720" in metadata or "720p" in metadata:
                        quality = 720
                    elif "540" in metadata:
                        quality = 540
                    elif "bitrate" in metadata:
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
            # Low-memory Chromium launch flags with automation stealth and autoplay enabled
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--disable-blink-features=AutomationControlled",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="it-IT",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"'
                }
            )

            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            # Abort heavy static assets (images, fonts) to save RAM, keeping stylesheet for proper DOM rendering
            def abort_heavy(route):
                rt = route.request.resource_type
                if rt in ["image", "font"]:
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", abort_heavy)
            page.on("response", on_response)

            try:
                page.goto(permalink, timeout=25000, wait_until="domcontentloaded")
            except Exception as ge:
                log_event("WARNING", f"Navigazione permalink lenta: {str(ge)}", reel_id=reel_id)

            page.wait_for_timeout(1000)
            log_event("INFO", f"Pagina Instagram caricata: URL={page.url}, Titolo={page.title()}", reel_id=reel_id)

            # Dismiss any login or cookie dialogs
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            cookie_selectors = [
                "button:has-text('Consenti tutti i cookie')",
                "button:has-text('Consenti tutti')",
                "button:has-text('Consenti')",
                "button:has-text('Accetta tutti')",
                "button:has-text('Accetta')",
                "button:has-text('Allow all cookies')",
                "button:has-text('Allow essential and optional cookies')",
                "button:has-text('Allow all')",
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
                "button:has-text('Alle Cookies erlauben')",
                "button:has-text('Nur notwendige Cookies erlauben')",
                "button:has-text('Nur erforderliche Cookies erlauben')",
                "button:has-text('Non ora')",
                "button:has-text('Not now')",
                "div[role='dialog'] button"
            ]
            for sel in cookie_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=1200)
                        page.wait_for_timeout(400)
                        break
                except Exception:
                    pass

            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # Unmute Instagram video player (React DASH audio stream is only fetched when unmuted)
            def try_unmute():
                return page.evaluate("""() => {
                    const sel = [
                        'svg[aria-label="Audio is muted"]',
                        'svg[aria-label*="muted" i]',
                        'svg[aria-label*="attiva audio" i]:not([aria-label*="disattiva" i])',
                        'svg[aria-label*="muto" i]',
                        'button[aria-label*="unmute" i]',
                        'button[aria-label*="attiva audio" i]:not([aria-label*="disattiva" i])'
                    ];
                    for (const s of sel) {
                        const el = document.querySelector(s);
                        if (el) {
                            const btn = el.closest("button") || el.closest("div[role='button']") || el;
                            btn.click();
                            return "Clicked: " + s;
                        }
                    }
                    document.querySelectorAll('video').forEach(v => {
                        v.muted = false;
                        v.volume = 1;
                        v.play().catch(() => {});
                    });
                    return null;
                }""")

            unmute_res = try_unmute()
            if unmute_res:
                log_event("INFO", f"Attivazione audio player Instagram: {unmute_res}", reel_id=reel_id)

            try:
                page.mouse.click(640, 400)
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

            # Wait for streams to arrive, re-trying unmute if audio not detected yet
            for i in range(16):
                if video_streams and audio_streams:
                    break
                if not audio_streams and i in (3, 6, 9):
                    try_unmute()
                    try:
                        page.mouse.click(640, 400)
                    except Exception:
                        pass
                page.wait_for_timeout(500)

            # Fallback: check og:video meta or video element src if streams were not captured via network
            if not video_streams:
                try:
                    direct_src = page.evaluate("""() => {
                        const meta = document.querySelector('meta[property="og:video"]');
                        if (meta && meta.content) return meta.content;
                        const v = document.querySelector('video');
                        if (v && v.src && v.src.startsWith('http')) return v.src;
                        return null;
                    }""")
                    if direct_src and ("fbcdn.net" in direct_src or ".mp4" in direct_src):
                        log_event("INFO", f"Trovato URL video diretto nel DOM/meta: {direct_src[:60]}...", reel_id=reel_id)
                        video_streams.append({"url": direct_src, "quality": 720})
                except Exception:
                    pass

            log_event("INFO", f"Risultato cattura stream: {len(video_streams)} video, {len(audio_streams)} audio", reel_id=reel_id)

            browser.close()

    except Exception as e:
        log_event("ERROR", f"Errore browser Chromium durante fallback per {reel_id}: {str(e)}", reel_id=reel_id)
        gc.collect()
        return {"success": False, "error": f"Errore browser: {str(e)}"}

    gc.collect()

    if not video_streams:
        return {"success": False, "error": "Nessun flusso video individuato nella pagina Instagram"}

    # For TikTok / mobile reels, 720p is optimal (super fast download and encoding, zero RAM/timeout issues)
    # Prefer 720p, or 540p; if none <= 720p, fall back to highest available
    p720_streams = [v for v in video_streams if v.get("quality", 0) <= 720]
    if p720_streams:
        p720_streams.sort(key=lambda x: x["quality"], reverse=True)
        chosen_video = p720_streams[0]["url"]
    else:
        video_streams.sort(key=lambda x: x["quality"], reverse=True)
        chosen_video = video_streams[0]["url"]

    chosen_audio = audio_streams[0]["url"] if audio_streams else None

    # Clean byte ranges to fetch complete media files
    def full_stream_url(url):
        parts = urllib.parse.urlsplit(url)
        query = "&".join(part for part in parts.query.split("&")
                         if urllib.parse.unquote(part.split("=", 1)[0]).lower()
                         not in {"bytestart", "byteend"})
        return urllib.parse.urlunsplit(parts._replace(query=query))

    clean_v_url = full_stream_url(chosen_video)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    tmp_v = DOWNLOADS_DIR / f"tmp_v_{reel_id}.mp4"
    tmp_a = DOWNLOADS_DIR / f"tmp_a_{reel_id}.m4a"
    dest_path = DOWNLOADS_DIR / f"{reel_id}.mp4"

    try:
        # Download video stream
        log_event("INFO", f"Download flusso video per Reel {reel_id}...", reel_id=reel_id)
        rv = requests.get(clean_v_url, headers=headers, stream=True, timeout=40)
        rv.raise_for_status()
        with open(tmp_v, "wb") as f:
            for chunk in rv.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        if chosen_audio:
            clean_a_url = full_stream_url(chosen_audio)
            log_event("INFO", f"Download traccia audio AAC per Reel {reel_id}...", reel_id=reel_id)
            ra = requests.get(clean_a_url, headers=headers, stream=True, timeout=30)
            ra.raise_for_status()
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
                "-map", "0:v:0", "-map", "1:a:0",
                "-threads", "1",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "24",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                "-shortest",
                str(dest_path)
            ]
        else:
            # A progressive MP4 may already contain audio; a video-only DASH
            # stream must fail rather than becoming a publishable silent file.
            validation = validate_video_audio(tmp_v)
            if not validation["success"]:
                raise ValueError("Nessun audio recuperabile da Instagram. Carica l'MP4 originale con audio.")
            cmd = [
                "ffmpeg", "-y",
                "-i", str(tmp_v),
                "-map", "0:v:0", "-map", "0:a:0",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                "-threads", "1",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-crf", "24",
                str(dest_path)
            ]

        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        validation = validate_video_audio(dest_path)
        if not validation["success"]:
            dest_path.unlink(missing_ok=True)
            raise ValueError(validation["error"])

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
