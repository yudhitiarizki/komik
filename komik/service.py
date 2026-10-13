"""Core logic: draft list sync, tracking (with initial full fetch) and update checks.
All functions take an open sqlite connection and a Source instance; they never
open connections themselves, so callers control transactions."""
import logging

from . import db

log = logging.getLogger("komik")


# --- sync_log helpers -------------------------------------------------------

def _log_start(conn, source, comic_id, kind):
    cur = conn.execute(
        "INSERT INTO sync_log(source, comic_id, kind, started_at) VALUES (?,?,?,?)",
        (source, comic_id, kind, db.now()),
    )
    conn.commit()  # keep the log row even if the sync itself fails and rolls back
    return cur.lastrowid


def _log_end(conn, log_id, ok, new_chapters=0, error=None):
    conn.execute(
        "UPDATE sync_log SET finished_at=?, ok=?, new_chapters=?, error=? WHERE id=?",
        (db.now(), int(ok), new_chapters, error, log_id),
    )
    conn.commit()


# --- upserts ----------------------------------------------------------------

def _upsert_list_item(conn, source, c):
    """Insert a draft or refresh the light fields; never overwrite detail data."""
    conn.execute(
        """INSERT INTO comics(source, source_comic_id, title, cover_url, latest_chapter)
           VALUES (?,?,?,?,?)
           ON CONFLICT(source, source_comic_id) DO UPDATE SET
             title = excluded.title,
             cover_url = CASE WHEN excluded.cover_url != '' THEN excluded.cover_url ELSE comics.cover_url END,
             latest_chapter = COALESCE(excluded.latest_chapter, comics.latest_chapter),
             updated_at = datetime('now')""",
        (source, c.id, c.title, c.cover_url, c.latest_chapter),
    )


def _apply_detail(conn, comic_pk, c):
    conn.execute(
        """UPDATE comics SET title=?, description=?, cover_url=CASE WHEN ?!='' THEN ? ELSE cover_url END,
           status=?, year=?, country=?, latest_chapter=COALESCE(?, latest_chapter),
           detail_fetched_at=?, updated_at=datetime('now') WHERE id=?""",
        (c.title, c.description, c.cover_url, c.cover_url, c.status, c.year, c.country,
         c.latest_chapter, db.now(), comic_pk),
    )
    for t in c.alt_titles:
        conn.execute("INSERT OR IGNORE INTO comic_alt_titles(comic_id, title) VALUES (?,?)", (comic_pk, t))
    for table, link, col, names in (("genres", "comic_genres", "genre_id", c.genres),
                                    ("authors", "comic_authors", "author_id", c.authors)):
        for name in names:
            conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name,))
            row = conn.execute(f"SELECT id FROM {table} WHERE name=?", (name,)).fetchone()
            conn.execute(f"INSERT OR IGNORE INTO {link}(comic_id, {col}) VALUES (?,?)", (comic_pk, row["id"]))


def _insert_new_chapters(conn, comic_pk, chapters):
    """Insert unknown chapters; returns the ones that were new."""
    known = {r["source_chapter_id"] for r in conn.execute(
        "SELECT source_chapter_id FROM chapters WHERE comic_id=?", (comic_pk,))}
    new = [ch for ch in chapters if ch.id not in known]
    conn.executemany(
        "INSERT INTO chapters(comic_id, source_chapter_id, number, title, released_at) VALUES (?,?,?,?,?)",
        [(comic_pk, ch.id, ch.number, ch.title, ch.released_at) for ch in new],
    )
    return new


# --- public operations ------------------------------------------------------

def sync_list(conn, src, pages=1, start_page=1):
    """Fetch list pages from a source and store them as drafts. Returns comics seen."""
    lid = _log_start(conn, src.name, None, "list")
    seen = 0
    try:
        page = start_page
        while page < start_page + pages:
            comics, total = src.list_comics(page)
            for c in comics:
                _upsert_list_item(conn, src.name, c)
            conn.commit()
            seen += len(comics)
            if page >= total or not comics:
                break
            page += 1
        _log_end(conn, lid, True)
        return seen
    except Exception as e:
        conn.rollback()
        _log_end(conn, lid, False, error=repr(e))
        raise


def initial_fetch(conn, src, comic_pk):
    """Fetch full detail + every chapter for a comic (first time it is tracked)."""
    row = conn.execute("SELECT * FROM comics WHERE id=?", (comic_pk,)).fetchone()
    lid = _log_start(conn, src.name, comic_pk, "initial")
    try:
        detail = src.get_comic(row["source_comic_id"])
        chapters = src.list_chapters(row["source_comic_id"])
        _apply_detail(conn, comic_pk, detail)
        new = _insert_new_chapters(conn, comic_pk, chapters)
        conn.execute("UPDATE comics SET last_checked_at=? WHERE id=?", (db.now(), comic_pk))
        conn.commit()
        _log_end(conn, lid, True, len(new))
        return len(new)
    except Exception as e:
        conn.rollback()
        _log_end(conn, lid, False, error=repr(e))
        raise


def track(conn, src, user_id, comic_pk, notify=True):
    """User picks a comic. The first time anyone picks it, fetch it in full."""
    row = conn.execute("SELECT * FROM comics WHERE id=?", (comic_pk,)).fetchone()
    if row is None:
        raise LookupError(f"comic {comic_pk} not found")
    if row["source"] != src.name:
        raise ValueError(f"comic {comic_pk} belongs to {row['source']}, not {src.name}")
    fetched = 0
    if row["detail_fetched_at"] is None:
        fetched = initial_fetch(conn, src, comic_pk)
    conn.execute(
        "INSERT OR IGNORE INTO user_tracking(user_id, comic_id, notify) VALUES (?,?,?)",
        (user_id, comic_pk, int(notify)),
    )
    conn.commit()
    return fetched


def check_comic(conn, src, comic_pk):
    """Look for new chapters of one tracked comic. Returns the list of new Chapters."""
    row = conn.execute("SELECT * FROM comics WHERE id=?", (comic_pk,)).fetchone()
    lid = _log_start(conn, src.name, comic_pk, "check")
    try:
        have = conn.execute("SELECT MAX(number) AS n FROM chapters WHERE comic_id=?", (comic_pk,)).fetchone()["n"]
        latest = src.quick_latest(row["source_comic_id"])
        if latest is not None and have is not None and latest <= have:
            new = []  # nothing newer on the site; skip the full chapter list
        else:
            new = _insert_new_chapters(conn, comic_pk, src.list_chapters(row["source_comic_id"]))
        conn.execute(
            "UPDATE comics SET last_checked_at=?, latest_chapter=COALESCE(?, latest_chapter) WHERE id=?",
            (db.now(), max([c.number for c in new], default=None), comic_pk),
        )
        conn.commit()
        _log_end(conn, lid, True, len(new))
        return new
    except Exception as e:
        conn.rollback()
        _log_end(conn, lid, False, error=repr(e))
        raise


def tracked_comics(conn, source):
    """Comics of a source that at least one user tracks, least recently checked first."""
    return conn.execute(
        """SELECT c.* FROM comics c
           WHERE c.source=? AND EXISTS (SELECT 1 FROM user_tracking t WHERE t.comic_id=c.id)
           ORDER BY c.last_checked_at IS NOT NULL, c.last_checked_at""",
        (source,),
    ).fetchall()


def check_source(conn, src):
    """Check every tracked comic of a source. One failing comic never stops the rest."""
    results = {}
    for row in tracked_comics(conn, src.name):
        try:
            new = check_comic(conn, src, row["id"])
        except Exception as e:  # logged in sync_log; keep going
            log.warning("check failed for %s/%s: %r", src.name, row["source_comic_id"], e)
            continue
        if new:
            results[row["id"]] = (row["title"], new)
            log.info("NEW %s: %s", row["title"], ", ".join(c.title or str(c.number) for c in new))
    return results


def mark_read(conn, user_id, comic_pk, number=None):
    """Mark chapters up to `number` (default: latest) as read for this user."""
    q = "SELECT id FROM chapters WHERE comic_id=? " + ("AND number<=? " if number is not None else "")
    q += "ORDER BY number DESC LIMIT 1"
    args = (comic_pk, number) if number is not None else (comic_pk,)
    row = conn.execute(q, args).fetchone()
    cur = conn.execute(
        "UPDATE user_tracking SET last_read_chapter_id=? WHERE user_id=? AND comic_id=?",
        (row["id"] if row else None, user_id, comic_pk),
    )
    conn.commit()
    return cur.rowcount > 0
