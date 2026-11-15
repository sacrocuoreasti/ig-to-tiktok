import gc
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from config import DOWNLOADS_DIR
from instagram_media import (
    empty_streams, merge_streams, network_stream, shortcode_from_url,
    streams_from_html, streams_from_payload,
)
from media_validation import validate_video_audio
from models import log_event

USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': USER_AGENT, 'Referer': 'https://www.instagram.com/',
           'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8'}


def _capture_browser_streams(permalink, reel_id):
    metadata = empty_streams()
    observed = empty_streams()

    def on_response(response):
        try:
            content_type = response.headers.get('content-type', '')
            if 'json' in content_type and urllib_host_is_instagram(response.url):
                merge_streams(metadata, streams_from_payload(response.json(), permalink))
            stream = network_stream(response.url, content_type)
            if stream:
                kind, item = stream
                merge_streams(observed, {kind: [item]})
        except Exception:
            # A failed/unrelated response must not abort extraction of the target.
            pass

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                  '--autoplay-policy=no-user-gesture-required'],
        )
        try:
            context = browser.new_context(user_agent=USER_AGENT, locale='it-IT',
                                          viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            page.route('**/*', lambda route: route.abort()
                       if route.request.resource_type in ('image', 'font') else route.continue_())
            page.on('response', on_response)
            shortcode = shortcode_from_url(permalink)
            urls = [permalink, f'https://www.instagram.com/p/{shortcode}/embed/']
            for url in urls:
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=25000)
                except Exception:
                    log_event('WARNING', 'Caricamento pagina Instagram lento; analizzo i metadati disponibili.', reel_id=reel_id)
                page.wait_for_timeout(1200)
                merge_streams(metadata, streams_from_html(page.content(), permalink))
                if metadata['video'] and metadata['audio']:
                    break
                for label in ('Consenti tutti i cookie', 'Consenti tutti', 'Allow all cookies',
                              'Allow all', 'Rifiuta cookie facoltativi', 'Decline optional cookies'):
                    try:
                        button = page.get_by_role('button', name=label, exact=True).first
                        if button.count() and button.is_visible():
                            button.click(timeout=1200)
                            break
                    except Exception:
                        pass
                page.keyboard.press('Escape')
                # Audio comes from the manifest even if the player never requests it.
                for attempt in range(10):
                    page.evaluate('''() => {
                        document.querySelectorAll('video').forEach(v => {
                            v.muted = false; v.volume = 1; v.play().catch(() => {});
                        });
                    }''')
                    page.wait_for_timeout(500)
                    if attempt in (0, 3, 9):
                        merge_streams(metadata, streams_from_html(page.content(), permalink))
                    if metadata['video'] and metadata['audio']:
                        break
                    if observed['video'] and observed['audio']:
                        break
                if metadata['video'] and metadata['audio']:
                    break
                if observed['video'] and observed['audio']:
                    break
            log_event('INFO',
                      f'Metadati del Reel: {len(metadata["video"])} video, '
                      f'{len(metadata["audio"])} audio, {len(metadata["progressive"])} MP4 completi; '
                      f'player: {len(observed["video"])} video, {len(observed["audio"])} audio.',
                      reel_id=reel_id)
        finally:
            browser.close()
    # Prefer the manifest of this exact Reel over anonymous requests by the player.
    if metadata['video'] and metadata['audio']:
        return metadata
    # Only pair player streams whose asset IDs agree; never mix suggested Reels.
    for video in observed['video']:
        matching = [audio for audio in observed['audio']
                    if video.get('asset_id') is not None and audio.get('asset_id') == video['asset_id']]
        if matching:
            return {'video': [video], 'audio': matching, 'progressive': metadata['progressive']}
    return metadata


def urllib_host_is_instagram(url):
    from urllib.parse import urlsplit
    host = urlsplit(url).hostname or ''
    return host == 'instagram.com' or host.endswith('.instagram.com')


def _preferred_video(streams):
    # Width, rather than portrait height, determines the 720p choice.
    limited = [s for s in streams if 0 < s.get('quality', 0) <= 720]
    return sorted(limited or streams, key=lambda s: s.get('quality', 0), reverse=bool(limited))


def _download_file(session, url, destination):
    with session.get(url, stream=True, timeout=(10, 40)) as response:
        response.raise_for_status()
        # A range response can be a partial file, even after removing URL ranges.
        if response.status_code != 200:
            raise ValueError('Instagram ha restituito un flusso parziale')
        with destination.open('wb') as output:
            for chunk in response.iter_content(65536):
                if chunk:
                    output.write(chunk)


def _mux_audio(video, audio, output):
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=codec_name,width,pix_fmt', '-of', 'json', str(video)],
        capture_output=True, text=True, check=True, timeout=20)
    import json
    stream = json.loads(probe.stdout)['streams'][0]
    command = ['ffmpeg', '-y', '-nostdin', '-v', 'error', '-i', str(video)]
    if audio:
        command += ['-i', str(audio)]
    command += ['-map', '0:v:0', '-map', '1:a:0' if audio else '0:a:0']
    if stream.get('codec_name') == 'h264' and stream.get('width', 9999) <= 720 and stream.get('pix_fmt') == 'yuv420p':
        command += ['-c:v', 'copy']
    else:
        command += ['-threads', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-vf', "scale=w='min(720,iw)':h=-2", '-preset', 'veryfast', '-crf', '24']
    command += ['-c:a', 'aac', '-ar', '44100', '-ac', '2', '-movflags', '+faststart', '-shortest', str(output)]
    subprocess.run(command, capture_output=True, check=True, timeout=120)


def _download_streams(streams, reel_id):
    destination = DOWNLOADS_DIR / f'{reel_id}.mp4'
    options = []
    if streams['video'] and streams['audio']:
        # Try alternate audio representations when a CDN rendition has expired.
        for audio in sorted(streams['audio'], key=lambda s: s.get('bandwidth', 0), reverse=True)[:3]:
            options.append((_preferred_video(streams['video'])[0]['url'], audio['url']))
    options.extend((video['url'], None) for video in _preferred_video(streams['progressive'])[:3])
    if not options:
        return {'success': False, 'error': 'Metadati audio del Reel non ancora disponibili da Instagram'}
    with requests.Session() as session, tempfile.TemporaryDirectory(prefix='reel-', dir=str(DOWNLOADS_DIR)) as tmp:
        session.headers.update(HEADERS)
        tmp = Path(tmp)
        for video_url, audio_url in options:
            try:
                video = tmp / 'video.mp4'
                audio = tmp / 'audio.m4a' if audio_url else None
                output = tmp / 'complete.mp4'
                _download_file(session, video_url, video)
                if audio:
                    _download_file(session, audio_url, audio)
                elif not validate_video_audio(video)['success']:
                    continue
                _mux_audio(video, audio, output)
                check = validate_video_audio(output)
                if not check['success']:
                    continue
                os.replace(output, destination)
                log_event('SUCCESS', f'Reel {reel_id}: audio recuperato automaticamente '
                          f'({check["audio_codec"]}, picco {check["peak_db"]} dB), MP4 pronto.', reel_id=reel_id)
                return {'success': True, 'file_path': str(destination),
                        'file_size': destination.stat().st_size, 'audio_verified': True}
            except (requests.RequestException, subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError):
                log_event('WARNING', 'Rappresentazione Instagram non disponibile; provo il flusso alternativo.', reel_id=reel_id)
    return {'success': False, 'error': 'Recupero audio Instagram temporaneamente non riuscito; il bot riproverà automaticamente'}


def download_reel_with_browser_fallback(permalink, reel_id):
    """Resolve audio from target-specific page manifests, then merge automatically."""
    if not shortcode_from_url(permalink):
        return {'success': False, 'error': 'Permalink Instagram non valido'}
    log_event('INFO', f'Recupero automatico video e audio del Reel {reel_id} dai metadati Instagram...', reel_id=reel_id)
    try:
        # Lightweight path first; no Chromium or audio playback is needed.
        try:
            response = requests.get(permalink, headers=HEADERS, timeout=(10, 15))
            response.raise_for_status()
            metadata = streams_from_html(response.text, permalink)
            if (metadata['video'] and metadata['audio']) or metadata['progressive']:
                result = _download_streams(metadata, reel_id)
                if result['success']:
                    return result
        except requests.RequestException:
            pass
        # Instagram may render the metadata only after JavaScript / cookie consent.
        metadata = _capture_browser_streams(permalink, reel_id)
        return _download_streams(metadata, reel_id)
    except Exception as error:
        log_event('WARNING', f'Estrazione Instagram da riprovare ({type(error).__name__}).', reel_id=reel_id)
        return {'success': False, 'error': 'Instagram non ha completato la risposta audio; nuovo tentativo automatico al prossimo controllo'}
    finally:
        gc.collect()
