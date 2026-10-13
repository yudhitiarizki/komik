"""Small REST API + static frontend.  Run: python manage.py serve"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import db, runtime, service
from .sources import SOURCES

log = logging.getLogger("komik.api")
WEB = Path(__file__).parent / "web"

UNREAD_SQL = """(SELECT COUNT(*) FROM chapters ch WHERE ch.comic_id=c.id AND ch.number >
                 COALESCE((SELECT number FROM chapters WHERE id=t.last_read_chapter_id), -1))"""


def create_app(db_path=None, scheduler=False, default_user=db.DEFAULT_USER):
    path = db_path or db.DEFAULT_PATH

    def get_conn():
        conn = db.connect(path)
        try:
            yield conn
        finally:
            conn.close()

    def get_uid(conn=Depends(get_conn), user: str = Query(default_user)):
        row = conn.execute("SELECT id FROM users WHERE username=?", (user,)).fetchone()
        if row is None:
            raise HTTPException(404, f"user '{user}' not found")
        return row["id"]

    @asynccontextmanager
    async def lifespan(app):
        with db.session(path) as conn:
            db.init(conn, SOURCES)  # idempotent; makes `serve` work on a fresh machine
        sched = None
        if scheduler:
            from apscheduler.schedulers.background import BackgroundScheduler

            def job(name):
                with db.session(path) as c, runtime.using(name) as src:
                    service.check_source(c, src)

            sched = BackgroundScheduler()
            with db.session(path) as conn:
                for r in conn.execute("SELECT name, check_interval_min FROM sources WHERE enabled=1"):
                    sched.add_job(job, "interval", minutes=r["check_interval_min"], args=[r["name"]],
                                  id=r["name"], max_instances=1, coalesce=True)
            sched.start()
            log.info("scheduler started")
        yield
        if sched:
            sched.shutdown(wait=False)

    app = FastAPI(title="komik", lifespan=lifespan)

    # ---- helpers ----------------------------------------------------------
    def comic_or_404(conn, comic_id):
        row = conn.execute("SELECT * FROM comics WHERE id=?", (comic_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "comic not found")
        return row

    # ---- routes -----------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/sources")
    def sources(conn=Depends(get_conn), uid=Depends(get_uid)):
        rows = conn.execute(
            """SELECT s.name, s.check_interval_min, s.enabled,
                      (SELECT COUNT(*) FROM comics c WHERE c.source=s.name) AS comics,
                      (SELECT COUNT(*) FROM user_tracking t JOIN comics c ON c.id=t.comic_id
                        WHERE c.source=s.name AND t.user_id=?) AS tracked
               FROM sources s ORDER BY s.name""", (uid,)).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/comics")
    def comics(scope: str = Query("drafts", pattern="^(drafts|tracked|all)$"), source: str | None = None,
               q: str | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
               conn=Depends(get_conn), uid=Depends(get_uid)):
        where, args = [], [uid]
        if scope == "drafts":
            where.append("t.user_id IS NULL")
        elif scope == "tracked":
            where.append("t.user_id IS NOT NULL")
        if source:
            where.append("c.source=?"); args.append(source)
        if q:
            where.append("c.title LIKE ?"); args.append(f"%{q}%")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        frm = "FROM comics c LEFT JOIN user_tracking t ON t.comic_id=c.id AND t.user_id=?"
        total = conn.execute(f"SELECT COUNT(*) {frm} {w}", args).fetchone()[0]
        order = "unread DESC, c.title" if scope == "tracked" else "c.updated_at DESC, c.id DESC"
        rows = conn.execute(
            f"""SELECT c.id, c.source, c.title, c.cover_url, c.status, c.latest_chapter,
                       c.detail_fetched_at IS NOT NULL AS detail_fetched, c.last_checked_at,
                       t.user_id IS NOT NULL AS tracked,
                       CASE WHEN t.user_id IS NULL THEN 0 ELSE {UNREAD_SQL} END AS unread
                {frm} {w} ORDER BY {order} LIMIT ? OFFSET ?""", [*args, limit, offset]).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    @app.get("/api/comics/{comic_id}")
    def comic(comic_id: int, conn=Depends(get_conn), uid=Depends(get_uid)):
        c = dict(comic_or_404(conn, comic_id))
        t = conn.execute("SELECT * FROM user_tracking WHERE user_id=? AND comic_id=?", (uid, comic_id)).fetchone()
        read_no = -1
        if t and t["last_read_chapter_id"]:
            r = conn.execute("SELECT number FROM chapters WHERE id=?", (t["last_read_chapter_id"],)).fetchone()
            read_no = r["number"] if r else -1
        c["tracked"] = t is not None
        c["alt_titles"] = [r[0] for r in conn.execute("SELECT title FROM comic_alt_titles WHERE comic_id=?", (comic_id,))]
        c["genres"] = [r[0] for r in conn.execute(
            "SELECT g.name FROM genres g JOIN comic_genres x ON x.genre_id=g.id WHERE x.comic_id=? ORDER BY g.name", (comic_id,))]
        c["authors"] = [r[0] for r in conn.execute(
            "SELECT a.name FROM authors a JOIN comic_authors x ON x.author_id=a.id WHERE x.comic_id=? ORDER BY a.name", (comic_id,))]
        c["chapters"] = [
            {**dict(r), "read": r["number"] <= read_no}
            for r in conn.execute(
                "SELECT id, number, title, released_at, discovered_at FROM chapters WHERE comic_id=? ORDER BY number DESC",
                (comic_id,))]
        return c

    @app.post("/api/comics/{comic_id}/track")
    def track(comic_id: int, conn=Depends(get_conn), uid=Depends(get_uid)):
        row = comic_or_404(conn, comic_id)
        first = row["detail_fetched_at"] is None
        try:
            with runtime.using(row["source"]) as src:
                service.track(conn, src, uid, comic_id)
        except Exception as e:
            log.exception("track failed")
            raise HTTPException(502, f"could not fetch from {row['source']}: {e!r}")
        n = conn.execute("SELECT COUNT(*) FROM chapters WHERE comic_id=?", (comic_id,)).fetchone()[0]
        return {"tracked": True, "first_fetch": first, "chapters": n}

    @app.delete("/api/comics/{comic_id}/track")
    def untrack(comic_id: int, conn=Depends(get_conn), uid=Depends(get_uid)):
        comic_or_404(conn, comic_id)
        conn.execute("DELETE FROM user_tracking WHERE user_id=? AND comic_id=?", (uid, comic_id))
        conn.commit()
        return {"tracked": False}

    @app.post("/api/comics/{comic_id}/read")
    def read(comic_id: int, upto: float | None = None, conn=Depends(get_conn), uid=Depends(get_uid)):
        comic_or_404(conn, comic_id)
        if not service.mark_read(conn, uid, comic_id, upto):
            raise HTTPException(409, "comic is not tracked")
        return {"ok": True}

    @app.get("/api/chapters/{chapter_id}/images")
    def chapter_images(chapter_id: int, conn=Depends(get_conn)):
        row = conn.execute(
            "SELECT ch.source_chapter_id, c.source FROM chapters ch JOIN comics c ON c.id=ch.comic_id WHERE ch.id=?",
            (chapter_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "chapter not found")
        try:
            with runtime.using(row["source"]) as src:
                return {"images": src.chapter_images(row["source_chapter_id"])}
        except Exception as e:
            log.exception("images failed")
            raise HTTPException(502, f"could not fetch images: {e!r}")

    @app.post("/api/sources/{name}/sync")
    def sync(name: str, pages: int = Query(1, ge=1, le=20), conn=Depends(get_conn)):
        if name not in SOURCES:
            raise HTTPException(404, "unknown source")
        try:
            with runtime.using(name) as src:
                return {"seen": service.sync_list(conn, src, pages=pages)}
        except Exception as e:
            log.exception("sync failed")
            raise HTTPException(502, f"sync failed: {e!r}")

    @app.post("/api/check")
    def check(source: str | None = None, conn=Depends(get_conn)):
        names = [source] if source else list(SOURCES)
        if any(n not in SOURCES for n in names):
            raise HTTPException(404, "unknown source")
        out = []
        for n in names:
            with runtime.using(n) as src:
                found = service.check_source(conn, src)
            out += [{"comic_id": cid, "title": title, "new": [c.title or str(c.number) for c in new]}
                    for cid, (title, new) in found.items()]
        return {"updates": out}

    @app.get("/api/log")
    def sync_log(limit: int = Query(20, ge=1, le=200), conn=Depends(get_conn)):
        return [dict(r) for r in conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,))]

    return app


app = create_app(scheduler=bool(os.environ.get("KOMIK_SCHEDULER")))
