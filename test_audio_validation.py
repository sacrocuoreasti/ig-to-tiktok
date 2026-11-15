"""Offline audio regression checks; never publish or contact an external API."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_validation import validate_video_audio
from tiktok_client import TikTokClient
from zernio_client import ZernioClient


class AudioValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = {}
        for name, audio in [("audible", "sine=frequency=440:sample_rate=44100"),
                            ("silent", "anullsrc=r=44100:cl=stereo"),
                            ("no_audio", None)]:
            path = Path(cls.tmp.name) / (name + ".mp4")
            cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=s=64x64:r=10"]
            if audio:
                cmd += ["-f", "lavfi", "-i", audio, "-c:a", "aac"]
            cmd += ["-t", "0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
            subprocess.run(cmd, check=True, capture_output=True)
            cls.files[name] = path
        cls.files["corrupt"] = Path(cls.tmp.name) / "corrupt.mp4"
        cls.files["corrupt"].write_bytes(b"not a video")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_audible_accepted(self):
        result = validate_video_audio(self.files["audible"])
        self.assertTrue(result["success"], result)
        self.assertEqual(result["audio_codec"], "aac")

    def test_invalid_audio_rejected(self):
        for name in ("silent", "no_audio", "corrupt"):
            with self.subTest(name=name):
                self.assertFalse(validate_video_audio(self.files[name])["success"])

    def test_missing_file_rejected(self):
        self.assertFalse(validate_video_audio(Path(self.tmp.name) / "missing.mp4")["success"])

    def test_verification_failures_never_allow_upload(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("ffprobe", 30),
                      subprocess.CalledProcessError(1, "ffprobe")):
            with self.subTest(error=type(error).__name__), patch("media_validation.subprocess.run", side_effect=error):
                self.assertFalse(validate_video_audio(self.files["audible"])["success"])

    def test_all_real_modes_block_silent_before_network(self):
        for mode in ("zernio", "web_session", "official_api"):
            with self.subTest(mode=mode), patch("tiktok_client.get_setting", return_value=""), \
                    patch("tiktok_client.log_event"), patch("tiktok_client.requests.post") as post:
                client = TikTokClient.__new__(TikTokClient)
                client.mode = mode
                client.format_caption = lambda caption: caption
                result = client.publish_video(str(self.files["silent"]))
                self.assertFalse(result["success"])
                post.assert_not_called()

    def test_direct_zernio_upload_blocks_silent_before_network(self):
        with patch("zernio_client.log_event"), patch("zernio_client.requests.post") as post:
            client = ZernioClient.__new__(ZernioClient)
            client.api_key = "offline-test"
            result = client.upload_media_file(str(self.files["silent"]))
            self.assertFalse(result["success"])
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
