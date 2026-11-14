"""A made-up, repeatable "world" for the simulator: accounts, campaigns, pages, IG accounts, posts and their results.

Everything is derived from a seed (account number, campaign number), so every run gives the same data.
Posts are laid out from WORLD_START to WORLD_END; the simulator shows only the ones before "now".
"""
from __future__ import annotations

import hashlib
import math
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

WORLD_START = date(2025, 9, 1)
WORLD_END = date(2027, 6, 30)
ACCOUNTS = 10

PRODUCTS = [("Poultry", "POULTRY"), ("Pork", "PORK"), ("Beef", "BEEF"), ("Milk", "DAIRY"), ("Cheese", "DAIRY"),
            ("Eggs", "POULTRY"), ("Honey", "PRODUCE"), ("Apples", "PRODUCE"), ("Rapeseed oil", "OILS"), ("Potatoes", "PRODUCE"),
            ("Groats", "GRAINS"), ("Freshwater fish", "FISH"), ("Lamb", "LAMB"), ("Butter", "DAIRY"), ("Yogurt", "DAIRY"),
            ("Bread", "GRAINS"), ("Vegetables", "PRODUCE"), ("Berries", "PRODUCE"), ("Turkey", "POULTRY"), ("Sausages", "PORK")]
SLOGANS = ["– a taste of quality", "– straight from the Polish countryside", "– the power of nature", "for every day",
           "– facts and myths", "in great kitchens", "– choose wisely", "– proven origin"]
TOPICS = [
    "How do you pick the best product in the shop? Check the origin and the certificates. ✅",
    "Facts and myths: we check with experts what really ends up on our tables. 🔍",
    "A weekend recipe: a quick dinner for the whole family in 30 minutes! 🍽️",
    "Behind the scenes at the farm: meet the people who look after quality every day. 🚜",
    "Contest! Tell us in the comments which dish reminds you of home. 🎁",
    "Seasonal and local: why buy from Polish producers? 🇵🇱",
    "How much protein do you need every day? A dietitian answers your questions. 💪",
    "See you at the fair! Come to our stand for a tasting. 📍",
    "Autumn cooking ideas: warming dishes for chilly evenings. 🍂",
    "Thank you for being with us! ❤️ It was a special weekend full of good conversations.",
    "Five things you didn't know about Polish farming. 🌾",
    "Breakfast of champions: ideas for a filling start to the day. ☀️",
]
HASHTAGS = "#EatLocal #PolishFarming #ProvenQuality #ProductsOfPoland"


def product_of(campaign_name: str) -> str:
    """The product a campaign is about (the name starts with it, e.g. "Rapeseed oil – proven origin")."""
    return next((p for p, _ in PRODUCTS if campaign_name.startswith(p + " ")), campaign_name.split(" ")[0])


def h(*parts) -> int:
    """A repeatable pseudo-random number from any parts (does not depend on PYTHONHASHSEED)."""
    return int(hashlib.md5("|".join(map(str, parts)).encode(), usedforsecurity=False).hexdigest()[:12], 16)


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def curve(hours: float, mid: float) -> float:
    """Share of results collected by a given hour after publishing (slow start, then a jump with promotion)."""
    if hours <= 0:
        return 0.0
    return 1 / (1 + math.exp(-(math.log(hours) - math.log(mid)) * 2.2))


@dataclass(frozen=True)
class Post:
    fb_id: str
    ig_id: str | None
    created: datetime
    text: str | None
    kind: str               # post | cover_photo | profile_media
    media_type: str         # IMAGE | CAROUSEL_ALBUM | VIDEO | REELS
    asset: str
    asset2: str
    views: int
    paid: float
    mid: float
    likes: int
    love: int
    comments: int
    shares: int
    clicks: int
    ig_views: int
    ig_reach: int
    ig_likes: int
    ig_comments: int
    ig_shares: int
    ig_saves: int
    ig_mid: float

    def share(self, now: datetime, ig: bool = False) -> float:
        return curve((now - self.created).total_seconds() / 3600, self.ig_mid if ig else self.mid)


@dataclass
class Campaign:
    account: int
    index: int
    id: str
    name: str
    label: str
    page_id: str
    ig_username: str | None
    ig_id: str | None
    ig_visible: bool
    start: date
    end: date | None
    fb_base: int
    fb_growth: float
    ig_base: int
    ig_growth: float
    bug_until: date | None      # until this date Meta's follower "history" is wrong (as in Supermetrics)
    bug_kind: str | None        # small | negative
    posts: list[Post] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ended" if self.end and self.end < date.today() else "active"

    def fb_followers(self, day: date) -> int:
        if day < self.start:
            return 0
        d = (day - self.start).days
        return int(self.fb_base + self.fb_growth * d + h(self.page_id, day) % 5)

    def meta_followers(self, day: date) -> int:
        """Follower count according to Meta's daily insights, with a deliberate error for new pages."""
        if self.bug_until and day <= self.bug_until:
            return -3 - h(self.page_id, day) % 4 if self.bug_kind == "negative" else 1 + h(self.page_id, day) % 3
        return self.fb_followers(day)

    def ig_followers(self, day: date) -> int:
        if day < self.start:
            return 0
        return int(self.ig_base + self.ig_growth * (day - self.start).days)

    def active(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass
class Account:
    number: int
    token: str
    name: str
    campaigns: list[Campaign]


def _posts(c: Campaign, rnd: random.Random) -> list[Post]:
    out: list[Post] = []
    stop = min(c.end or WORLD_END, WORLD_END)
    day = c.start + timedelta(days=2)
    n = 0
    # Profile and cover photo changes: Meta shows them as posts (a trap known from Supermetrics).
    first = datetime.combine(c.start + timedelta(days=1), time(13, 40), tzinfo=timezone.utc)
    changes = [(first, "profile_media"), (first, "cover_photo")]
    if c.start + timedelta(days=200) < stop:
        changes.append((datetime.combine(c.start + timedelta(days=200), time(9, 5), tzinfo=timezone.utc), "cover_photo"))
    for created, kind in changes:
        out.append(_post(c, rnd, n, created, kind))
        n += 1
    while day <= stop:
        hour = rnd.choice([8, 9, 10, 11, 14, 15])
        created = datetime.combine(day, time(hour, rnd.choice([0, 0, 1, 15, 30])), tzinfo=timezone.utc)
        out.append(_post(c, rnd, n, created, "post"))
        n += 1
        day += timedelta(days=rnd.choice([3, 3, 4, 4, 5]))
    return sorted(out, key=lambda p: p.created)


def _post(c: Campaign, rnd: random.Random, n: int, created: datetime, kind: str) -> Post:
    product = product_of(c.name)
    if kind == "post":
        topic = TOPICS[(c.index * 7 + n) % len(TOPICS)]
        text = f"{product}: {topic}"
        if rnd.random() < 0.35:
            text += ("\n\nYou'll find more on our website. Let us know in the comments "
                     "what you'd like to see in the next posts! 👇")
        text += f"\n\n{HASHTAGS}"
    else:
        text = None
    promoted = kind == "post" and (c.end is None or created.date() < c.end - timedelta(days=30))
    views = rnd.randint(250, 700) if kind != "post" else (rnd.randint(12000, 26000) if promoted else rnd.randint(300, 2500))
    likes = rnd.randint(0, 14) if kind == "post" else rnd.randint(3, 10)
    has_ig = c.ig_id is not None and kind == "post"
    media_type = rnd.choice(["IMAGE", "IMAGE", "CAROUSEL_ALBUM", "VIDEO", "REELS"]) if has_ig else "IMAGE"
    return Post(
        fb_id=f"{c.page_id}_{100000 + n}",
        ig_id=f"{c.ig_id}{n:05d}" if has_ig else None,
        created=created, text=text, kind=kind, media_type=media_type,
        asset=f"{c.page_id}_{n}_a_n", asset2=f"{c.page_id}_{n}_b_n",
        views=views, paid=rnd.uniform(0.95, 0.997) if promoted else 0.0, mid=rnd.uniform(18, 160),
        likes=likes, love=rnd.choice([0, 0, 1, 2]), comments=rnd.choice([0, 0, 0, 1, 1, 2, 3]),
        shares=rnd.choice([0, 0, 0, 1, 1, 2, 5]), clicks=rnd.randint(0, 9),
        ig_views=rnd.randint(80, 1400), ig_reach=rnd.randint(40, 700),
        ig_likes=rnd.randint(0, 60 if c.index % 5 == 0 else 8), ig_comments=rnd.choice([0, 0, 0, 1]),
        ig_shares=rnd.choice([0, 0, 1, 2]), ig_saves=rnd.choice([0, 1, 2, 3]), ig_mid=rnd.uniform(2, 30),
    )


@lru_cache(maxsize=None)
def account(number: int) -> Account:
    if not 1 <= number <= ACCOUNTS:
        raise ValueError(f"A test account number must be 1–{ACCOUNTS}")
    combos = [(p, s) for p in PRODUCTS for s in SLOGANS]
    random.Random("metastat-fake").shuffle(combos)
    rnd = random.Random(f"account-{number}")
    count = 12 + rnd.randint(0, 4)
    taken = sum(12 + random.Random(f"account-{k}").randint(0, 4) for k in range(1, number))
    campaigns = []
    for i in range(count):
        (product, label), slogan = combos[(taken + i) % len(combos)]
        name = f"{product} {slogan}".replace("  ", " ")
        crnd = random.Random(f"campaign-{number}-{i}")
        page_id = str(100000000000000 + number * 10_000_000 + i * 10_000 + 7)
        has_ig = i % 7 != 3                 # some campaigns without Instagram
        ig_visible = has_ig and i % 9 != 5  # and one "private" IG account, invisible to the API
        start = WORLD_START
        bug_until = bug_kind = None
        if i % 6 == 4:                      # new page: starts later and has a broken follower history
            start = date(2026, 8, 1) + timedelta(days=i * 3)
            bug_until, bug_kind = start + timedelta(days=20), ("negative" if i % 2 else "small")
        end = date(2026, 5, 31) if i % 8 == 6 else (date(2026, 9, 30) if i % 8 == 7 else None)
        c = Campaign(
            account=number, index=i, id=f"t{number:02d}-{slug(name)}"[:60], name=name, label=label,
            page_id=page_id, ig_username=slug(name)[:27].rstrip("_") + f"_{number:02d}" if has_ig else None,  # IG: 30 characters at most
            ig_id=f"1784{number:02d}{i:02d}" if has_ig else None, ig_visible=ig_visible,
            start=start, end=end, fb_base=crnd.randint(150, 9000), fb_growth=crnd.choice([0.2, 1, 2.5, 6, 11]),
            ig_base=crnd.randint(0, 900), ig_growth=crnd.choice([0, 0.3, 0.8, 2]),
            bug_until=bug_until, bug_kind=bug_kind)
        c.posts = _posts(c, crnd)
        campaigns.append(c)
    return Account(number=number, token=f"fake-token-{number:02d}", name=f"Test account {number:02d} (simulator)",
                   campaigns=campaigns)


def by_token(token: str | None) -> Account | None:
    m = re.fullmatch(r"fake-token-(\d{2})", token or "")
    if m and 1 <= int(m.group(1)) <= ACCOUNTS:
        return account(int(m.group(1)))
    m = re.fullmatch(r"pt-(\d+)", token or "")      # page token
    if m:
        for n in range(1, ACCOUNTS + 1):
            if any(c.page_id == m.group(1) for c in account(n).campaigns):
                return account(n)
    return None
