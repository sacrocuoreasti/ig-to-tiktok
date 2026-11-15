"""Read the requested Reel's media manifest, independently of player requests."""
import base64
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


def shortcode_from_url(permalink):
    match = re.search(r"/(?:reels?|p|tv)/([^/?#]+)", permalink or "")
    return match.group(1) if match else None


def full_stream_url(url):
    parts = urllib.parse.urlsplit(url)
    query = "&".join(p for p in parts.query.split("&")
                     if urllib.parse.unquote(p.split("=", 1)[0]).lower()
                     not in {"bytestart", "byteend"})
    return urllib.parse.urlunsplit(parts._replace(query=query))


def is_media_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        return parts.scheme == "https" and any(
            host == domain or host.endswith("." + domain)
            for domain in ("fbcdn.net", "cdninstagram.com"))
    except (ValueError, TypeError):
        return False


def merge_streams(target, source):
    for kind in ("video", "audio", "progressive"):
        for stream in source.get(kind, []):
            if is_media_url(stream.get("url")):
                stream = dict(stream, url=full_stream_url(stream["url"]))
                if not any(s["url"] == stream["url"] for s in target[kind]):
                    target[kind].append(stream)
    return target


def empty_streams():
    return {"video": [], "audio": [], "progressive": []}


def streams_from_manifest(manifest):
    streams = empty_streams()
    try:
        root = ET.fromstring(manifest)
    except (ET.ParseError, TypeError):
        return streams
    for adaptation in root.findall(".//{*}AdaptationSet"):
        for rep in adaptation.findall("{*}Representation"):
            mime = rep.get("mimeType", adaptation.get("mimeType", ""))
            kind = rep.get("contentType", adaptation.get("contentType", "")) or mime.split("/")[0]
            if kind not in ("video", "audio"):
                continue
            base = rep.find("{*}BaseURL")
            if base is None:
                base = adaptation.find("{*}BaseURL")
            if base is not None and is_media_url(base.text):
                streams[kind].append({
                    "url": full_stream_url(base.text),
                    "quality": int(rep.get("width", "0")),
                    "bandwidth": int(rep.get("bandwidth", "0")),
                    "source": "manifest",
                })
    return streams


def streams_from_payload(payload, permalink):
    """Never attach audio from recommended posts to the requested Reel."""
    streams = empty_streams()
    shortcode = shortcode_from_url(permalink)
    if not shortcode:
        return streams
    pending = [payload]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            pending.extend(v for v in node.values() if isinstance(v, (dict, list)))
            if node.get("code", node.get("shortcode")) != shortcode:
                continue
            manifest = node.get("video_dash_manifest") or node.get("dash_manifest")
            if manifest:
                try:
                    merge_streams(streams, streams_from_manifest(manifest))
                except (ValueError, TypeError):
                    pass
            for version in node.get("video_versions") or []:
                if is_media_url(version.get("url")):
                    streams["progressive"].append({"url": version["url"], "quality": version.get("width", 0)})
            if is_media_url(node.get("video_url")):
                streams["progressive"].append({"url": node["video_url"], "quality": 0})
    return merge_streams(empty_streams(), streams)


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inside = True
            self.parts = []

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.inside:
            self.scripts.append("".join(self.parts))
            self.inside = False


def streams_from_html(html, permalink):
    parser = _Scripts()
    parser.feed(html)
    streams = empty_streams()
    for script in parser.scripts:
        try:
            merge_streams(streams, streams_from_payload(json.loads(script), permalink))
        except (ValueError, TypeError):
            continue
    return streams


def network_stream(url, content_type):
    if not is_media_url(url):
        return None
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    encoded = params.get("efg", [""])[0]
    try:
        meta = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError, UnicodeError):
        meta = {}
    tag = str(meta.get("vencode_tag", "")).lower()
    if "audio" in content_type or any(s in tag for s in ("audio", "aac", "opus")) or ".m4a" in url:
        kind = "audio"
    elif "video" in content_type:
        kind = "video"
    else:
        return None
    return kind, {"url": full_stream_url(url), "quality": 0,
                  "asset_id": meta.get("xpv_asset_id"), "source": "player"}
