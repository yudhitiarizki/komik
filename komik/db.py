import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources

DEFAULT_PATH = os.environ.get("KOMIK_DB", "data/komik.db")
DEFAULT_USER = "local"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None):
    path = path or DEFAULT_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(path=None):
    """Connection that commits on success and rolls back on error."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init(conn, sources):
    """Create tables, seed the sources table and the default local user."""
    conn.executescript(resources.files("komik").joinpath("schema.sql").read_text(encoding="utf-8"))
    for name, cls in sources.items():
        conn.execute("INSERT OR IGNORE INTO sources(name, base_url) VALUES (?, ?)", (name, getattr(cls, "site", None)))
    conn.execute("INSERT OR IGNORE INTO users(username) VALUES (?)", (DEFAULT_USER,))
    conn.commit()
