"""Downloads post images right during the sync, because Meta's signed links (the oe parameter) expire.

The original stays unchanged; a JPG copy about 800 px wide is made for reports.
The same image on FB and IG (cross-posts) is stored once: by the Meta asset file name,
and when the names differ, by identical content (SHA-256).
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import sqlite3
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx
from PIL import Image

from metastat import db
from metastat.paths import ensure_dir

log = logging.getLogger(__name__)

EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/heic": ".heic"}


def asset_key(url: str) -> str:
    """The Meta asset file name from a CDN URL, e.g. 466912345_1234_n.jpg (without the signature parameters)."""
    name = PurePosixPath(urlparse(url).path).name or hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)


def _https_only(request: httpx.Request) -> None:
    if request.url.scheme != "https":
        raise httpx.UnsupportedProtocol(f"Images are downloaded over https only (host: {request.url.host})", request=request)


def download_client(**kw) -> httpx.Client:
    """Client for images from Meta's CDN: redirects allowed, but every request, also after a redirect, is https only."""
    from metastat import net
    return net.client(follow_redirects=True, event_hooks={"request": [_https_only]}, **kw)


class ImageStore:
    def __init__(self, data_dir: Path, conn: sqlite3.Connection, *, client: httpx.Client | None = None,
                 report_width: int = 800, jpeg_quality: int = 85):
        self.data_dir = data_dir
        self.conn = conn
        self.client = client or download_client()
        self.report_width = report_width
        self.jpeg_quality = jpeg_quality
        self.downloaded = 0
        self.failed = 0

    def ensure(self, url: str | None, platform: str, post_id: str) -> str | None:
        """Returns the image_id (downloads it if needed). None when there is no image or the download failed."""
        if not url:
            return None
        if not url.startswith("https://"):                  # URL from the API: no http://, file:// and the like
            self.failed += 1
            log.warning("Skipped image %s %s: the URL is not https", platform, post_id)
            return None
        key = asset_key(url)
        if self.conn.execute("SELECT 1 FROM images WHERE image_id = ?", (key,)).fetchone():
            return key
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            self.failed += 1
            log.warning("Could not download image %s %s: %s (will retry at the next sync)", platform, post_id, e)
            return None
        content = resp.content
        sha = hashlib.sha256(content).hexdigest()
        same = self.conn.execute("SELECT image_id FROM images WHERE sha256 = ?", (sha,)).fetchone()
        if same:
            return same["image_id"]

        ext = EXT_BY_TYPE.get(resp.headers.get("content-type", "").split(";")[0].strip()) or PurePosixPath(key).suffix or ".jpg"
        stem = f"{platform}_{_safe(post_id)}"
        original = Path("images") / "original" / f"{stem}{ext}"
        report = Path("images") / f"w{self.report_width}" / f"{stem}.jpg"
        ensure_dir((self.data_dir / original).parent)
        ensure_dir((self.data_dir / report).parent)
        (self.data_dir / original).write_bytes(content)

        try:
            with Image.open(io.BytesIO(content)) as im:
                width, height = im.size
                im = im.convert("RGB")
                if im.width > self.report_width:
                    im = im.resize((self.report_width, round(im.height * self.report_width / im.width)), Image.LANCZOS)
                im.save(self.data_dir / report, "JPEG", quality=self.jpeg_quality, optimize=True)
        except Exception as e:  # broken or unsupported format: only the original is kept
            log.warning("Could not resize image %s: %s", original, e)
            width = height = None
            report = original

        db.upsert(self.conn, "images", {
            "image_id": key, "sha256": sha, "source_url": url,
            "original_path": original.as_posix(), "report_path": report.as_posix(),
            "width": width, "height": height, "downloaded_utc": db.now_utc(),
        }, ["image_id"])
        self.downloaded += 1
        return key
