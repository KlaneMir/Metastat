-- Database schema. Metrics are kept in long format (object, time, metric, value),
-- because Meta renames metrics and we do not want a migration for every change.
-- Time: *_utc in ISO 8601 UTC, *_local in Europe/Warsaw, date = local day YYYY-MM-DD.

CREATE TABLE IF NOT EXISTS campaigns (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  label        TEXT,
  status       TEXT NOT NULL,
  fb_page_id   TEXT,
  ig_username  TEXT,
  updated_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fb_pages (
  page_id      TEXT PRIMARY KEY,
  campaign_id  TEXT NOT NULL REFERENCES campaigns(id),
  name         TEXT,
  username     TEXT,
  link         TEXT,
  ig_user_id   TEXT,
  updated_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fb_page_daily (
  page_id      TEXT NOT NULL,
  date         TEXT NOT NULL,
  metric       TEXT NOT NULL,
  value        REAL,
  raw          TEXT,             -- raw value (e.g. split by reaction type, paid/organic)
  source       TEXT NOT NULL,    -- insights | field
  fetched_utc  TEXT NOT NULL,
  PRIMARY KEY (page_id, date, metric)
);

CREATE TABLE IF NOT EXISTS fb_posts (
  post_id          TEXT PRIMARY KEY,
  page_id          TEXT NOT NULL,
  created_utc      TEXT NOT NULL,
  created_local    TEXT NOT NULL,
  status_type      TEXT,
  attachment_type  TEXT,
  kind             TEXT NOT NULL,   -- post | profile_photo | cover_photo
  message          TEXT,
  permalink        TEXT,
  picture_url      TEXT,
  image_id         TEXT REFERENCES images(image_id),
  first_seen_utc   TEXT NOT NULL,
  last_seen_utc    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fb_posts_page_created ON fb_posts(page_id, created_utc);

CREATE TABLE IF NOT EXISTS fb_post_snapshots (
  post_id    TEXT NOT NULL,
  taken_utc  TEXT NOT NULL,
  metric     TEXT NOT NULL,
  value      REAL,
  raw        TEXT,
  PRIMARY KEY (post_id, taken_utc, metric)
);

CREATE TABLE IF NOT EXISTS ig_accounts (
  ig_user_id   TEXT PRIMARY KEY,
  campaign_id  TEXT NOT NULL REFERENCES campaigns(id),
  username     TEXT,
  name         TEXT,
  page_id      TEXT,
  updated_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ig_account_daily (
  ig_user_id   TEXT NOT NULL,
  date         TEXT NOT NULL,
  metric       TEXT NOT NULL,
  value        REAL,
  raw          TEXT,
  source       TEXT NOT NULL,
  fetched_utc  TEXT NOT NULL,
  PRIMARY KEY (ig_user_id, date, metric)
);

CREATE TABLE IF NOT EXISTS ig_media (
  media_id            TEXT PRIMARY KEY,
  ig_user_id          TEXT NOT NULL,
  created_utc         TEXT NOT NULL,
  created_local       TEXT NOT NULL,
  media_type          TEXT,
  media_product_type  TEXT,
  caption             TEXT,
  permalink           TEXT,
  picture_url         TEXT,
  image_id            TEXT REFERENCES images(image_id),
  first_seen_utc      TEXT NOT NULL,
  last_seen_utc       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ig_media_user_created ON ig_media(ig_user_id, created_utc);

CREATE TABLE IF NOT EXISTS ig_media_snapshots (
  media_id   TEXT NOT NULL,
  taken_utc  TEXT NOT NULL,
  metric     TEXT NOT NULL,
  value      REAL,
  raw        TEXT,
  PRIMARY KEY (media_id, taken_utc, metric)
);

CREATE TABLE IF NOT EXISTS images (
  image_id        TEXT PRIMARY KEY,  -- file name of the Meta asset (FB/IG deduplication)
  sha256          TEXT NOT NULL,
  source_url      TEXT,
  original_path   TEXT NOT NULL,     -- relative to data/
  report_path     TEXT NOT NULL,
  width           INTEGER,
  height          INTEGER,
  downloaded_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS images_sha ON images(sha256);

CREATE TABLE IF NOT EXISTS metric_support (
  scope        TEXT NOT NULL,   -- e.g. fb_post, fb_page_day, ig_media:REELS
  metric       TEXT NOT NULL,
  ok           INTEGER NOT NULL,
  error        TEXT,
  checked_utc  TEXT NOT NULL,
  PRIMARY KEY (scope, metric)
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  mode          TEXT NOT NULL,
  started_utc   TEXT NOT NULL,
  finished_utc  TEXT,
  status        TEXT NOT NULL,   -- running | ok | partial | failed
  api_calls     INTEGER,
  summary       TEXT,
  error         TEXT
);

CREATE TABLE IF NOT EXISTS flags (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  scope        TEXT NOT NULL,   -- fb_page | ig_account | fb_post | ig_media | campaign
  object_id    TEXT NOT NULL,
  date         TEXT NOT NULL,
  kind         TEXT NOT NULL,
  detail       TEXT,
  created_utc  TEXT NOT NULL,
  UNIQUE (scope, object_id, date, kind)
);
