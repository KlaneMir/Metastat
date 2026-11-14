"""Photos for test posts: free photos from Wikimedia Commons with a "TEST" watermark.

`metastat fake photos` downloads once a set of food and farm produce photos (2 per product
of the test campaigns) into src/metastat/fakeapi/stock/. The simulator then gives every post a photo
that matches the campaign's product, with a watermark and the post number (so every file is different).

Only free licenses are used: CC0, public domain, CC BY and CC BY-SA. The author and license are on every
photo (CC BY licenses require it) and in the stock/photos.json file.
"""
from __future__ import annotations

import html
import io
import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

STOCK_DIR = Path(__file__).parent / "stock"
MANIFEST = STOCK_DIR / "photos.json"
SIZE = (720, 900)
API = "https://commons.wikimedia.org/w/api.php"
FONT_FILES = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
FREE = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? \d)", re.I)

# test campaign product → Commons search
QUERIES = {
    "Poultry": "roast chicken dish", "Pork": "pork dish plate", "Beef": "beef steak", "Milk": "glass of milk",
    "Cheese": "cheese board", "Eggs": "chicken eggs basket", "Honey": "honey jar", "Apples": "apples orchard harvest",
    "Rapeseed oil": "rapeseed oil bottle", "Potatoes": "potatoes harvest", "Groats": "buckwheat groats",
    "Freshwater fish": "carp fish dish", "Lamb": "lamb chops", "Butter": "butter dairy", "Yogurt": "yogurt bowl",
    "Bread": "bread bakery loaves", "Vegetables": "vegetables market stall", "Berries": "blueberries basket",
    "Turkey": "roast turkey", "Sausages": "sausages grill",
}


def _text(v) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(v or "")))).strip()


def _get(client, url: str, params: dict | None = None, out=print):
    """GET with a pause (Wikimedia limits the rate) and retries after 429 / 5xx."""
    import time
    for attempt in range(5):
        time.sleep(1.2)
        r = client.get(url, params=params)
        if r.status_code not in (429, 500, 502, 503, 504):
            return r
        wait = int(r.headers.get("retry-after") or 0) or 20 * (attempt + 1)
        out(f"  the server asks for a pause, waiting {wait} s…")
        time.sleep(wait)
    r.raise_for_status()
    return r


def download(per_product: int = 2, out=print) -> Path:
    """Downloads the photos (720×900 JPG) and records the author, license and source of each one.

    Can be interrupted and run again: products that already have photos are skipped.
    """
    from metastat import net
    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    client = net.client(follow_redirects=True, headers={"User-Agent": "Metastat-test-photos/0.1 (test tool)"})
    items = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    items = [x for x in items if (STOCK_DIR / x["file"]).exists()]
    for product, query in QUERIES.items():
        if sum(1 for x in items if x["product"] == product) >= per_product:
            continue
        r = _get(client, API, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 25,
            "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime", "iiurlwidth": SIZE[0]}, out=out)
        r.raise_for_status()
        pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        got = 0
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = _text((meta.get("LicenseShortName") or {}).get("value"))
            if info.get("mime") != "image/jpeg" or not FREE.match(lic) or (info.get("width") or 0) < SIZE[0]:
                continue
            if any(x.get("title") == p.get("title") for x in items):
                continue
            target = STOCK_DIR / f"{len(items) + 1:02d}_{re.sub(r'[^a-z0-9]+', '_', query)}.jpg"
            img = _get(client, info.get("thumburl") or info["url"], out=out)
            if img.status_code != 200 or not img.headers.get("content-type", "").startswith("image/"):
                continue
            with Image.open(io.BytesIO(img.content)) as im:
                ImageOps.fit(im.convert("RGB"), SIZE, Image.LANCZOS).save(target, "JPEG", quality=88)
            items.append({"file": target.name, "product": product, "title": p.get("title"),
                          "author": _text((meta.get("Artist") or {}).get("value"))[:60] or "unknown author",
                          "license": lic, "source": info.get("descriptionurl")})
            got += 1
            if got + sum(1 for x in items[:-got] if x["product"] == product) >= per_product:
                break
        MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")  # saved after each product
        out(f"  {product}: {sum(1 for x in items if x['product'] == product)} photos")
    size = sum((STOCK_DIR / x["file"]).stat().st_size for x in items)
    out(f"Downloaded {len(items)} photos ({size / 1024 / 1024:.1f} MB) from Wikimedia Commons to {STOCK_DIR}")
    pool.cache_clear()
    return STOCK_DIR


@lru_cache(maxsize=1)
def pool() -> list[dict]:
    if not MANIFEST.exists():
        return []
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [x for x in items if (STOCK_DIR / x["file"]).exists()]


@lru_cache(maxsize=8)
def _font(size: int):
    for name in FONT_FILES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=64)
def _base(file: str) -> bytes:
    return (STOCK_DIR / file).read_bytes()


def watermarked(item: dict, label: str) -> bytes:
    """Watermarked photo: a diagonal "TEST" and a strip with the author credit and the post number."""
    im = Image.open(io.BytesIO(_base(item["file"]))).convert("RGB")
    if im.size != SIZE:
        im = im.resize(SIZE)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    big = _font(118)
    text = "TEST"
    w = d.textlength(text, font=big)
    mark = Image.new("RGBA", (int(w) + 40, 170), (0, 0, 0, 0))
    ImageDraw.Draw(mark).text((20, 10), text, font=big, fill=(255, 255, 255, 92))
    mark = mark.rotate(28, expand=True)
    layer.alpha_composite(mark, ((SIZE[0] - mark.width) // 2, (SIZE[1] - mark.height) // 2 - 40))
    d.rectangle([0, SIZE[1] - 64, SIZE[0], SIZE[1]], fill=(20, 20, 20, 170))
    d.text((22, SIZE[1] - 52), "TEST PHOTO", font=_font(19), fill=(255, 255, 255, 235))
    credit = f"photo: {item['author']} · {item['license']} · Wikimedia Commons · {label}"
    d.text((22, SIZE[1] - 28), credit[:95], font=_font(15), fill=(230, 230, 225, 220))
    out = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=84)
    return buf.getvalue()
