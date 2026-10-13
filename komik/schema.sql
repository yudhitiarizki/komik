PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    name               TEXT PRIMARY KEY,
    base_url           TEXT,
    check_interval_min INTEGER NOT NULL DEFAULT 10,
    enabled            INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS comics (
    id                INTEGER PRIMARY KEY,
    source            TEXT NOT NULL REFERENCES sources(name),
    source_comic_id   TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    cover_url         TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT '',
    year              TEXT NOT NULL DEFAULT '',
    country           TEXT NOT NULL DEFAULT '',
    latest_chapter    REAL,
    detail_fetched_at TEXT,             -- NULL = draft (only list-page data)
    last_checked_at   TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, source_comic_id)
);
CREATE INDEX IF NOT EXISTS idx_comics_source ON comics(source);

CREATE TABLE IF NOT EXISTS comic_alt_titles (
    id       INTEGER PRIMARY KEY,
    comic_id INTEGER NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    title    TEXT NOT NULL,
    UNIQUE (comic_id, title)
);

CREATE TABLE IF NOT EXISTS genres  (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS comic_genres (
    comic_id INTEGER NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (comic_id, genre_id)
);
CREATE TABLE IF NOT EXISTS comic_authors (
    comic_id  INTEGER NOT NULL REFERENCES comics(id)  ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    PRIMARY KEY (comic_id, author_id)
);

CREATE TABLE IF NOT EXISTS chapters (
    id                INTEGER PRIMARY KEY,
    comic_id          INTEGER NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    source_chapter_id TEXT NOT NULL,
    number            REAL NOT NULL,
    title             TEXT NOT NULL DEFAULT '',
    released_at       TEXT NOT NULL DEFAULT '',   -- text as shown by the site
    discovered_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (comic_id, source_chapter_id)
);
CREATE INDEX IF NOT EXISTS idx_chapters_comic_number ON chapters(comic_id, number);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT UNIQUE,
    password_hash TEXT,                 -- NULL = local user without login
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_tracking (
    user_id              INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    comic_id             INTEGER NOT NULL REFERENCES comics(id) ON DELETE CASCADE,
    tracked_at           TEXT NOT NULL DEFAULT (datetime('now')),
    notify               INTEGER NOT NULL DEFAULT 1,
    last_read_chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, comic_id)
);
CREATE INDEX IF NOT EXISTS idx_user_tracking_comic ON user_tracking(comic_id);

CREATE TABLE IF NOT EXISTS sync_log (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL REFERENCES sources(name),
    comic_id     INTEGER REFERENCES comics(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('list', 'initial', 'check')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    ok           INTEGER NOT NULL DEFAULT 0,
    new_chapters INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);
