PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artists (
    artist_id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    site_user_id TEXT,
    handle TEXT NOT NULL,
    display_name TEXT,
    profile_url TEXT,
    avatar_url TEXT,
    header_url TEXT,
    bio TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    nsfw INTEGER,
    accepts_commissions INTEGER,
    works_count INTEGER,
    followers_count INTEGER,
    rating REAL,
    first_seen REAL NOT NULL,
    last_updated REAL NOT NULL,
    last_seen REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    raw_hash TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_artists_site_handle
    ON artists(site, handle COLLATE NOCASE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_artists_site_user_id
    ON artists(site, site_user_id)
    WHERE site_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_artists_site_updated
    ON artists(site, last_updated);

CREATE TABLE IF NOT EXISTS artist_handles (
    artist_id TEXT NOT NULL REFERENCES artists(artist_id) ON DELETE CASCADE,
    handle TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY (artist_id, handle)
);

CREATE TABLE IF NOT EXISTS offerings (
    offering_id TEXT PRIMARY KEY,
    artist_id TEXT NOT NULL REFERENCES artists(artist_id) ON DELETE CASCADE,
    site TEXT NOT NULL,
    site_offering_id TEXT,
    title TEXT,
    kind TEXT,
    description TEXT,
    price_min INTEGER,
    price_max INTEGER,
    currency TEXT NOT NULL DEFAULT 'JPY',
    price_usd REAL,
    price_min_usd REAL,
    price_max_usd REAL,
    cover_url TEXT,
    turnaround_days INTEGER,
    slots INTEGER,
    available INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]',
    source_url TEXT,
    first_seen REAL NOT NULL,
    last_updated REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

DROP INDEX IF EXISTS idx_offerings_site_site_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_offerings_artist_site_id
    ON offerings(site, artist_id, site_offering_id)
    WHERE site_offering_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_offerings_artist
    ON offerings(artist_id);
CREATE INDEX IF NOT EXISTS idx_offerings_site_price
    ON offerings(site, price_min_usd);

CREATE TABLE IF NOT EXISTS works (
    work_id TEXT PRIMARY KEY,
    artist_id TEXT NOT NULL REFERENCES artists(artist_id) ON DELETE CASCADE,
    site TEXT NOT NULL,
    site_work_id TEXT,
    title TEXT,
    thumb_url TEXT,
    image_urls_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL,
    source_url TEXT,
    first_seen REAL NOT NULL,
    last_updated REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_works_artist
    ON works(artist_id);
CREATE INDEX IF NOT EXISTS idx_works_site_created
    ON works(site, created_at);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offering_id TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    amount INTEGER,
    currency TEXT NOT NULL,
    amount_usd REAL,
    observed_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_history_offering
    ON price_history(offering_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_price_history_artist
    ON price_history(artist_id, observed_at);

CREATE TABLE IF NOT EXISTS frontier (
    site TEXT NOT NULL,
    handle TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at REAL NOT NULL DEFAULT 0,
    last_run_at REAL,
    last_error TEXT,
    PRIMARY KEY (site, handle)
);

CREATE INDEX IF NOT EXISTS idx_frontier_due
    ON frontier(site, status, next_run_at, priority);

CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    fetched_at REAL,
    status INTEGER,
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    content_hash TEXT NOT NULL,
    body BLOB NOT NULL,
    UNIQUE(site, kind, key, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_raw_payloads_lookup
    ON raw_payloads(site, kind, key, fetched_at);
