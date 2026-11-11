import os
import re
import time
import gc
from pathlib import Path
from playwright.sync_api import sync_playwright
from models import get_setting, log_event
from config import DATA_DIR

def clean_session_id(val):
    if not val:
        return ""
    val = val.strip().strip('"').strip("'")
    if "sessionid=" in val:
        match = re.search(r'sessionid=([^;]+)', val)
        if match:
            val = match.group(1).strip()
    return val

def test_tiktok_cookie(session_id):
    """
    Tests if a given TikTok sessionid cookie is valid by navigating to Creator Center.
    Returns: {"valid": True/False, "message": str}
    """
    session_id = clean_session_id(session_id)

    if not session_id or len(session_id) < 10:
        return {"valid": False, "message": "Il sessionid inserito è vuoto o troppo corto. Verifica di averlo copiato correttamente."}

    gc.collect()
    try:
        with sync_playwright() as p:
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
                    "--disable-blink-features=AutomationControlled",
                    "--js-flags=--max-old-space-size=128"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-US"
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
            """)

            # Inject cookies
            cookies = [
                {"name": "sessionid", "value": session_id, "domain": ".tiktok.com", "path": "/"},
                {"name": "sessionid_ss", "value": session_id, "domain": ".tiktok.com", "path": "/"}
            ]
            context.add_cookies(cookies)

            page = context.new_page()

            # Abort heavy assets
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font", "media"] else route.continue_())

            page.goto("https://www.tiktok.com/creator-center/upload?from=upload", timeout=35000, wait_until="domcontentloaded")
            time.sleep(3)

            current_url = page.url
            browser.close()

            if "login" in current_url:
                return {
                    "valid": False,
                    "message": "Cookie non valido o sessione scaduta (reindirizzato alla pagina di login)."
                }

            if "creator-center" in current_url or "creator" in current_url or "upload" in current_url or "studio" in current_url:
                return {
                    "valid": True,
                    "message": "Sessione TikTok valida e autenticata! Pronto per la pubblicazione."
                }

            return {
                "valid": True,
                "message": "Connessione a TikTok riuscita."
            }

    except Exception as e:
        return {"valid": False, "message": f"Errore durante la verifica del cookie: {str(e)}"}
    finally:
        gc.collect()


def upload_to_tiktok_via_web(video_path, caption="", privacy_level="PUBLIC_TO_EVERYONE", session_id=None):
    """
    Uploads a video to TikTok Creator Studio using Playwright and sessionid cookie.
    Optimized for low-RAM containers with navigation resilience and timeout prevention.
    """
    if not session_id:
        session_id = get_setting("tiktok_session_id", "")

    session_id = clean_session_id(session_id)

    if not session_id:
        return {"success": False, "error": "Nessun cookie sessionid di TikTok configurato nelle impostazioni."}

    if not os.path.exists(video_path):
        return {"success": False, "error": f"File video non trovato: {video_path}"}

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        return {"success": False, "error": "File video vuoto o non valido"}

    log_event("INFO", f"Avvio caricamento TikTok Studio per {os.path.basename(video_path)} ({file_size // 1024} KB)...")

    debug_screenshot = DATA_DIR / "debug_tiktok.png"
    gc.collect()

    try:
        with sync_playwright() as p:
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
                    "--disable-blink-features=AutomationControlled",
                    "--js-flags=--max-old-space-size=128"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 850},
                locale="en-US"
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
            """)

            # Inject session cookies
            cookies = [
                {"name": "sessionid", "value": session_id, "domain": ".tiktok.com", "path": "/"},
                {"name": "sessionid_ss", "value": session_id, "domain": ".tiktok.com", "path": "/"}
            ]
            context.add_cookies(cookies)

            page = context.new_page()

            # Abort fonts and media to save memory, allow scripts and xhr
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["font"] else route.continue_())

            # Navigate to TikTok Studio upload page
            upload_url = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
            log_event("INFO", f"Apertura pagina di upload TikTok Studio...")
            page.goto(upload_url, timeout=45000, wait_until="domcontentloaded")

            # Allow initial SPA / redirects to settle
            try:
                page.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            time.sleep(2)

            # Helper to dismiss popups, cookie consent, onboarding dialogs
            def dismiss_overlays():
                overlay_texts = [
                    "Alle erlauben", "Optionale Cookies ablehnen", "Accetta tutti",
                    "Accept all", "Got it", "OK", "Continua", "Ho capito", "Chiudi",
                    "Manage cookies", "Decline optional"
                ]
                for txt in overlay_texts:
                    try:
                        b = page.locator(f"button:has-text('{txt}')").first
                        if b.count() > 0 and b.is_visible():
                            b.click(timeout=1000)
                            time.sleep(0.3)
                    except Exception:
                        pass

            dismiss_overlays()

            # Check if redirected to login
            if "login" in page.url:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                err_msg = "Cookie di sessione scaduto o non valido (reindirizzato a login). Aggiorna TIKTOK_SESSION_ID nelle impostazioni."
                log_event("ERROR", err_msg)
                return {"success": False, "error": err_msg}

            # Locate file input across all frames with retry loop
            log_event("INFO", "Ricerca del campo di caricamento video su TikTok Studio...")
            target = page
            file_input = None

            for attempt in range(15):
                dismiss_overlays()
                # Check all frames
                for frame in page.frames:
                    try:
                        loc = frame.locator("input[type='file']")
                        if loc.count() > 0:
                            file_input = loc.first
                            target = frame
                            break
                    except Exception:
                        pass
                if file_input:
                    break

                # Check main page
                try:
                    loc = page.locator("input[type='file']")
                    if loc.count() > 0:
                        file_input = loc.first
                        target = page
                        break
                except Exception:
                    pass

                time.sleep(1.5)

            if not file_input:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                return {"success": False, "error": "Timeout: campo di caricamento file non trovato su TikTok Studio."}

            log_event("INFO", "Invio file video al caricatore di TikTok...")
            # Use no_wait_after=True to prevent 30s timeout waiting for SPA navigation
            file_input.set_input_files(os.path.abspath(video_path), no_wait_after=True, timeout=20000)

            # Wait for video upload to process (look for caption box or progress)
            log_event("INFO", "Attesa elaborazione video su TikTok Studio...")
            time.sleep(8)

            # Re-check target context in case page updated
            if page.locator("iframe").count() > 0:
                for frame in page.frames:
                    try:
                        if frame.locator("div[contenteditable='true']").count() > 0:
                            target = frame
                            break
                    except Exception:
                        pass

            # Find caption editor
            caption_selectors = [
                "div[contenteditable='true']",
                ".notranslate[contenteditable='true']",
                "[data-placeholder]",
                "div.public-DraftEditor-content"
            ]

            caption_box = None
            for sel in caption_selectors:
                try:
                    loc = target.locator(sel)
                    if loc.count() > 0:
                        caption_box = loc.first
                        break
                except Exception:
                    pass

            if caption_box and caption:
                log_event("INFO", "Inserimento didascalia nel video...")
                try:
                    caption_box.click(timeout=3000)
                    time.sleep(0.5)
                    # Clear existing content if any
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                    time.sleep(0.3)
                    # Type caption
                    caption_box.type(caption[:2000], delay=10)
                except Exception as ce:
                    log_event("WARNING", f"Avviso inserimento didascalia: {str(ce)}")

            # Handle privacy level if necessary
            if privacy_level == "SELF_ONLY":
                try:
                    priv_btn = target.locator("text='Chi può vedere questo video'").first
                    if priv_btn.count() > 0:
                        priv_btn.click()
                        time.sleep(0.5)
                        only_me = target.locator("text='Solo io'").first
                        if only_me.count() > 0:
                            only_me.click()
                except Exception:
                    pass

            # Remove Joyride onboarding tour overlay and any interfering backdrops
            try:
                page.evaluate("""() => {
                    const joyride = document.getElementById('react-joyride-portal');
                    if (joyride) joyride.remove();
                    document.querySelectorAll('.react-joyride__overlay, [data-test-id="overlay"], .portal-container').forEach(el => el.remove());
                    // Click skip or finish on any tour if present
                    const skipBtn = document.querySelector('button[aria-label="Skip"], button[aria-label="Close"], button[data-action="skip"]');
                    if (skipBtn) skipBtn.click();
                }""")
            except Exception:
                pass

            time.sleep(2)

            # Locate Post / Pubblica button (excluding sidebar navigation items)
            post_button_selectors = [
                "button.btn-post",
                "button[data-tt*='post' i]:not([data-tt*='Sidebar'])",
                "button[data-tt*='publish' i]:not([data-tt*='Sidebar'])",
                "button:has-text('Pubblica'):not([data-tt*='Sidebar']):not([class*='Sidebar'])",
                "button:has-text('Post'):not([data-tt*='Sidebar']):not([class*='Sidebar'])",
                "button[type='button']:has-text('Pubblica')",
                "button[type='button']:has-text('Post')"
            ]

            post_btn = None
            for sel in post_button_selectors:
                try:
                    btn_loc = target.locator(sel)
                    for i in range(btn_loc.count()):
                        cand = btn_loc.nth(i)
                        data_tt = cand.get_attribute("data-tt") or ""
                        cls = cand.get_attribute("class") or ""
                        if "Sidebar" not in data_tt and "Sidebar" not in cls and cand.is_visible():
                            post_btn = cand
                            break
                    if post_btn:
                        break
                except Exception:
                    pass

            if not post_btn:
                # Try finding in main page
                for sel in post_button_selectors:
                    try:
                        btn_loc = page.locator(sel)
                        for i in range(btn_loc.count()):
                            cand = btn_loc.nth(i)
                            data_tt = cand.get_attribute("data-tt") or ""
                            cls = cand.get_attribute("class") or ""
                            if "Sidebar" not in data_tt and "Sidebar" not in cls and cand.is_visible():
                                post_btn = cand
                                break
                        if post_btn:
                            break
                    except Exception:
                        pass

            if not post_btn:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                return {"success": False, "error": "Pulsante 'Pubblica' non trovato dopo il caricamento."}

            log_event("INFO", "Pulsante 'Pubblica' individuato. Clicco per pubblicare...")
            post_btn.click(timeout=8000, force=True)

            # Wait for publication confirmation
            time.sleep(6)
            page.screenshot(path=str(debug_screenshot))
            browser.close()

            publish_id = f"web_pub_{int(time.time())}"
            log_event("SUCCESS", f"Video pubblicato con successo su TikTok tramite Web Studio! ID: {publish_id}")
            return {
                "success": True,
                "publish_id": publish_id,
                "status": "PUBLISHED_WEB_STUDIO",
                "mode": "web_session"
            }

    except Exception as e:
        log_event("ERROR", f"Errore durante upload TikTok Web: {str(e)}")
        return {"success": False, "error": str(e)}
    finally:
        gc.collect()
