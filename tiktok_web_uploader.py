import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from models import get_setting, log_event
from config import DATA_DIR

def test_tiktok_cookie(session_id):
    """
    Tests if a given TikTok sessionid cookie is valid by navigating to Creator Center.
    Returns: {"valid": True/False, "message": str}
    """
    if not session_id or len(session_id.strip()) < 10:
        return {"valid": False, "message": "Il sessionid inserito è troppo corto o non valido."}

    session_id = session_id.strip()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )

            # Inject cookies
            cookies = [
                {"name": "sessionid", "value": session_id, "domain": ".tiktok.com", "path": "/"},
                {"name": "sessionid_ss", "value": session_id, "domain": ".tiktok.com", "path": "/"}
            ]
            context.add_cookies(cookies)

            page = context.new_page()
            page.goto("https://www.tiktok.com/creator-center/upload", timeout=35000, wait_until="domcontentloaded")
            time.sleep(3)

            current_url = page.url
            page_content = page.content()

            browser.close()

            if "login" in current_url:
                return {
                    "valid": False,
                    "message": "Il cookie sessionid sembra scaduto o non valido (reindirizzato alla pagina di login)."
                }

            if "creator-center" in current_url or "creator" in current_url or "upload" in current_url:
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


def upload_to_tiktok_via_web(video_path, caption="", privacy_level="PUBLIC_TO_EVERYONE", session_id=None):
    """
    Uploads a video to TikTok Creator Center using Playwright and the authenticated sessionid cookie.
    """
    if not session_id:
        session_id = get_setting("tiktok_session_id", "").strip()

    if not session_id:
        return {"success": False, "error": "Nessun cookie sessionid di TikTok configurato nelle impostazioni."}

    if not os.path.exists(video_path):
        return {"success": False, "error": f"File video non trovato: {video_path}"}

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        return {"success": False, "error": "File video vuoto o non valido"}

    log_event("INFO", f"Avvio caricamento TikTok Web Studio per {os.path.basename(video_path)} ({file_size // 1024} KB)...")

    debug_screenshot = DATA_DIR / "debug_tiktok.png"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 900}
            )

            # Inject session cookies
            cookies = [
                {"name": "sessionid", "value": session_id, "domain": ".tiktok.com", "path": "/"},
                {"name": "sessionid_ss", "value": session_id, "domain": ".tiktok.com", "path": "/"}
            ]
            context.add_cookies(cookies)

            page = context.new_page()

            # Navigate to TikTok Studio upload page
            page.goto("https://www.tiktok.com/creator-center/upload?from=upload", timeout=45000, wait_until="domcontentloaded")
            time.sleep(4)

            # Check if redirected to login
            if "login" in page.url:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                err_msg = "Cookie di sessione scaduto o non valido. Aggiorna il sessionid nelle impostazioni."
                log_event("ERROR", err_msg)
                return {"success": False, "error": err_msg}

            # Locate file input (could be in page or within an iframe)
            target = page
            if page.locator("iframe").count() > 0:
                for frame in page.frames:
                    if frame.locator("input[type='file']").count() > 0:
                        target = frame
                        break

            file_input = target.locator("input[type='file']").first
            if not file_input:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                return {"success": False, "error": "Impossibile trovare il campo di caricamento video su TikTok Studio."}

            log_event("INFO", "Invio file video al caricatore di TikTok...")
            file_input.set_input_files(os.path.abspath(video_path))

            # Wait for video upload to process (look for caption box or progress)
            log_event("INFO", "Attesa caricamento ed elaborazione video...")
            time.sleep(8)

            # Re-check target context in case page updated
            if page.locator("iframe").count() > 0:
                for frame in page.frames:
                    if frame.locator("div[contenteditable='true']").count() > 0:
                        target = frame
                        break

            # Find caption editor
            caption_selectors = [
                "div[contenteditable='true']",
                ".notranslate[contenteditable='true']",
                "[data-placeholder]",
                "div.public-DraftEditor-content"
            ]

            caption_box = None
            for sel in caption_selectors:
                loc = target.locator(sel)
                if loc.count() > 0:
                    caption_box = loc.first
                    break

            if caption_box and caption:
                log_event("INFO", "Inserimento didascalia ed hashtag nel video...")
                try:
                    caption_box.click()
                    time.sleep(0.5)
                    # Clear existing content if any
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                    time.sleep(0.3)
                    # Type caption
                    caption_box.type(caption, delay=10)
                except Exception as ce:
                    log_event("WARNING", f"Avviso inserimento didascalia: {str(ce)}")

            # Handle privacy level if necessary
            # TikTok Studio default is Public ("Tutti" / "Public")
            if privacy_level == "SELF_ONLY":
                try:
                    # Look for privacy dropdown
                    priv_btn = target.locator("text='Chi può vedere questo video'").first
                    if priv_btn.count() > 0:
                        priv_btn.click()
                        time.sleep(0.5)
                        only_me = target.locator("text='Solo io'").first
                        if only_me.count() > 0:
                            only_me.click()
                except Exception:
                    pass

            time.sleep(4)

            # Locate Post / Pubblica button
            post_button_selectors = [
                "button:has-text('Pubblica')",
                "button:has-text('Post')",
                "button.btn-post",
                "button[type='button']:has-text('Pubblica')",
                "button[type='button']:has-text('Post')"
            ]

            post_btn = None
            for sel in post_button_selectors:
                btn_loc = target.locator(sel)
                if btn_loc.count() > 0 and btn_loc.first.is_visible():
                    post_btn = btn_loc.first
                    break

            if not post_btn:
                # Try finding in page
                for sel in post_button_selectors:
                    btn_loc = page.locator(sel)
                    if btn_loc.count() > 0 and btn_loc.first.is_visible():
                        post_btn = btn_loc.first
                        break

            if not post_btn:
                page.screenshot(path=str(debug_screenshot))
                browser.close()
                return {"success": False, "error": "Pulsante 'Pubblica' non trovato dopo il caricamento."}

            # Check if post button is enabled
            log_event("INFO", "Pulsante 'Pubblica' trovato. Clicco per pubblicare...")
            post_btn.click()

            # Wait for publication confirmation (up to 20 seconds)
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
        log_event("ERROR", f"Errore durante l'upload TikTok Web: {str(e)}")
        return {"success": False, "error": str(e)}

