"""Reject unverified, missing or silent audio before sending videos to TikTok."""
import json
import math
import re
import subprocess
from pathlib import Path


def validate_video_audio(file_path, check_signal=True):
    if not file_path or not Path(file_path).is_file():
        return {"success": False, "error": "File video mancante"}
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
             "-of", "json", str(file_path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        streams = json.loads(probe.stdout).get("streams", [])
        if not any(s.get("codec_type") == "video" for s in streams):
            return {"success": False, "error": "Il file non contiene un flusso video"}
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        if not audio:
            return {"success": False, "error": "Video senza traccia audio: pubblicazione bloccata"}
        result = {"success": True, "audio_codec": audio[0].get("codec_name")}
        if check_signal:
            decoded = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-xerror",
                 "-i", str(file_path), "-map", "0:a:0", "-vn", "-sn",
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, check=True, timeout=120,
            )
            peak = re.search(r"max_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB", decoded.stderr)
            if not peak:
                return {"success": False, "error": "Segnale audio non verificabile: pubblicazione bloccata"}
            peak_db = float(peak.group(1))
            if not math.isfinite(peak_db) or peak_db <= -80:
                return {"success": False, "error": "Traccia audio silenziosa: pubblicazione bloccata"}
            result["peak_db"] = peak_db
        return result
    except FileNotFoundError:
        return {"success": False, "error": "ffprobe/ffmpeg non disponibile: impossibile verificare l'audio"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Verifica audio scaduta: pubblicazione bloccata"}
    except (subprocess.CalledProcessError, ValueError, TypeError, AttributeError, OSError):
        return {"success": False, "error": "Video o audio non leggibile: pubblicazione bloccata"}
