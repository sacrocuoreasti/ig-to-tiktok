import json
import unittest
from unittest.mock import MagicMock, patch

from instagram_media import (empty_streams, full_stream_url, network_stream,
                             streams_from_html, streams_from_payload)
from instagram_scraper import _capture_browser_streams, download_reel_with_browser_fallback


URL = 'https://www.instagram.com/reel/De6xTECO2mH/'
MANIFEST = '''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
<AdaptationSet mimeType="video/mp4"><Representation width="720" bandwidth="1000000">
<BaseURL>https://cdn.fbcdn.net/target-video.mp4?token=a%2Fb</BaseURL></Representation></AdaptationSet>
<AdaptationSet contentType="audio" mimeType="audio/mp4"><Representation bandwidth="64000">
<BaseURL>https://cdn.fbcdn.net/target-audio.mp4?x=1&amp;bytestart=0&amp;byteend=500</BaseURL>
</Representation></AdaptationSet></Period></MPD>'''


def page_html():
    return '<script type="application/json" data-sjs>' + json.dumps({
        'require': [{'code': 'De6xTECO2mH', 'video_dash_manifest': MANIFEST},
                    {'code': 'OTHER', 'video_dash_manifest': MANIFEST.replace('target-', 'wrong-')}]
    }) + '</script>'


class InstagramMediaTests(unittest.TestCase):
    def test_explicit_licensing_refusal_is_reported_without_download(self):
        from instagram_scraper import _download_streams
        streams = empty_streams()
        streams['audio_blocked_reason'] = 'Licenza non disponibile'
        with patch('instagram_scraper.requests.Session') as session, patch('instagram_scraper.log_event'):
            result = _download_streams(streams, 'test')
        self.assertTrue(result['audio_unavailable'])
        self.assertIn('Licenza non disponibile', result['error'])
        session.assert_not_called()

    def test_extracts_target_audio_even_without_player_requests(self):
        streams = streams_from_html(page_html(), URL)
        self.assertEqual(len(streams['audio']), 1)
        self.assertEqual(len(streams['video']), 1)
        self.assertIn('target-audio.mp4?x=1', streams['audio'][0]['url'])
        self.assertNotIn('wrong-', str(streams))

    def test_browser_recovers_manifest_without_unmuting_player(self):
        browser = MagicMock()
        page = browser.new_context.return_value.new_page.return_value
        page.content.return_value = page_html()
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser
        with patch('instagram_scraper.sync_playwright') as factory, patch('instagram_scraper.log_event'):
            factory.return_value.__enter__.return_value = playwright
            streams = _capture_browser_streams(URL, 'test')
        self.assertEqual(len(streams['audio']), 1)
        # Only inspect codecs; do not unmute or play the video to discover audio.
        page.evaluate.assert_called_once()
        self.assertIn('canPlayType', page.evaluate.call_args.args[0])
        browser.close.assert_called_once()

    def test_only_other_reel_returns_no_streams(self):
        self.assertEqual(streams_from_payload({'code': 'OTHER', 'video_dash_manifest': MANIFEST}, URL), empty_streams())

    def test_untrusted_media_urls_rejected(self):
        self.assertEqual(streams_from_payload({'code': 'De6xTECO2mH', 'video_url': 'https://fbcdn.net.evil.example/video.mp4'}, URL), empty_streams())

    def test_malformed_manifest_does_not_lose_progressive_fallback(self):
        result = streams_from_payload({'shortcode': 'De6xTECO2mH', 'video_dash_manifest': 'invalid XML',
                                       'video_url': 'https://cdn.fbcdn.net/full.mp4'}, URL)
        self.assertEqual(len(result['progressive']), 1)

    def test_ranges_removed_independently_and_signature_preserved(self):
        self.assertEqual(full_stream_url('https://cdn.fbcdn.net/a?byteend=10&token=a%2Fb&bytestart=0'),
                         'https://cdn.fbcdn.net/a?token=a%2Fb')

    def test_audio_tag_uses_urlsafe_base64(self):
        import base64
        meta = {'vencode_tag': 'dash_ln_heaac_vbr3_audio', 'xpv_asset_id': 123}
        encoded = base64.urlsafe_b64encode(json.dumps(meta).encode()).decode().rstrip('=')
        kind, stream = network_stream('https://cdn.fbcdn.net/audio.mp4?efg=' + encoded, 'video/mp4')
        self.assertEqual(kind, 'audio')
        self.assertEqual(stream['asset_id'], 123)

    def test_http_manifest_path_skips_browser(self):
        response = MagicMock(text=page_html())
        with patch('instagram_scraper.requests.get', return_value=response), \
                patch('instagram_scraper._capture_browser_streams') as browser, \
                patch('instagram_scraper._download_streams', return_value={'success': True, 'audio_verified': True}) as download, \
                patch('instagram_scraper.log_event'):
            result = download_reel_with_browser_fallback(URL, 'test')
        self.assertTrue(result['audio_verified'])
        self.assertTrue(download.call_args.args[0]['audio'])
        browser.assert_not_called()

    def test_missing_manifest_tries_browser_automatically(self):
        response = MagicMock(text='<html>no manifest</html>')
        streams = streams_from_html(page_html(), URL)
        with patch('instagram_scraper.requests.get', return_value=response), \
                patch('instagram_scraper._capture_browser_streams', return_value=streams) as browser, \
                patch('instagram_scraper._download_streams', return_value={'success': True, 'audio_verified': True}), \
                patch('instagram_scraper.log_event'):
            result = download_reel_with_browser_fallback(URL, 'test')
        self.assertTrue(result['audio_verified'])
        browser.assert_called_once()

    def test_sync_retries_audio_failures_but_not_previous_publications(self):
        from bot_service import BotService
        for publish_id, expected_downloads in [(None, 1), ('already-published', 0)]:
            with self.subTest(publish_id=publish_id), \
                    patch('bot_service.log_event'), \
                    patch('bot_service.get_setting', return_value='false'), \
                    patch('bot_service.InstagramClient') as ig, \
                    patch('bot_service.TikTokClient'), \
                    patch('bot_service.save_or_update_reel', return_value=(False, 'audio_restricted')), \
                    patch('bot_service.get_reel', return_value={'tiktok_publish_id': publish_id}), \
                    patch('bot_service.update_reel_status'), \
                    patch('instagram_scraper.download_reel_with_browser_fallback',
                          return_value={'success': True, 'file_path': 'ready.mp4'}) as download:
                ig.return_value.fetch_recent_reels.return_value = {
                    'success': True, 'reels': [{'id': 'test', 'permalink': URL}]}
                result = BotService().run_sync_cycle()
                self.assertEqual(result['downloaded_count'], expected_downloads)
                self.assertEqual(download.call_count, expected_downloads)

    def test_download_endpoint_recovers_audio_without_publishing(self):
        # Import with startup disabled so this offline test never runs a real bot.
        with patch('models.init_db'), patch('models.get_setting', return_value='false'):
            from app import app
        client = app.test_client()
        with client.session_transaction() as session:
            session['logged_in'] = True
        with patch('app.get_reel', return_value={'id': 'test', 'status': 'published',
                                               'media_url': 'expired', 'permalink': URL}), \
                patch('app.InstagramClient') as ig, \
                patch('media_validation.validate_video_audio', return_value={'success': False}), \
                patch('instagram_scraper.download_reel_with_browser_fallback',
                      return_value={'success': True, 'file_path': 'ready.mp4', 'audio_verified': True}) as download, \
                patch('models.update_reel_status') as update, \
                patch('app.bot.publish_single_reel') as publish:
            ig.return_value.download_video.return_value = {'success': True, 'file_path': 'silent.mp4'}
            response = client.post('/api/reels/test/download')
        self.assertTrue(response.get_json()['audio_verified'])
        download.assert_called_once_with(URL, 'test')
        publish.assert_not_called()
        self.assertEqual(update.call_args.args[1], 'published')


if __name__ == '__main__':
    unittest.main()
