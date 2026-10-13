#!/usr/bin/env python3
"""Database-backed tracker. The raw scraping CLI is still cli.py.

  python manage.py init
  python manage.py sync-list komiku --pages 3     # fill the draft list
  python manage.py drafts --source komiku --q ao  # browse drafts
  python manage.py track 12                       # pick a comic (first pick fetches everything)
  python manage.py tracked                        # your comics + unread counts
  python manage.py check [--source komiku]        # one update check now
  python manage.py serve [--scheduler]            # web UI + API at http://127.0.0.1:8000
  python manage.py run                            # scheduler: checks every source on its interval
  python manage.py read 12 [--chapter 40]         # mark as read
  python manage.py untrack 12
  python manage.py log                            # recent sync history
"""
import argparse
import logging
import sys
from datetime import datetime

from komik import db, service
from komik.sources import SOURCES


def make_source(name, delay):
    return SOURCES[name](delay=delay)


def user_id(conn, username):
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row is None:
        sys.exit(f"user '{username}' not found (create it with: user-add {username})")
    return row["id"]


def comic_row(conn, comic_pk):
    row = conn.execute("SELECT * FROM comics WHERE id=?", (comic_pk,)).fetchone()
    if row is None:
        sys.exit(f"comic {comic_pk} not found")
    return row


def cmd_init(a, conn):
    db.init(conn, SOURCES)
    print(f"database ready at {a.db or db.DEFAULT_PATH} (default user '{db.DEFAULT_USER}')")


def cmd_user_add(a, conn):
    conn.execute("INSERT INTO users(username, email) VALUES (?,?)", (a.username, a.email))
    conn.commit()
    print(f"user '{a.username}' created")


def cmd_sync_list(a, conn):
    n = service.sync_list(conn, make_source(a.source, a.delay), pages=a.pages)
    print(f"{n} comics seen from {a.source} (stored as drafts unless already known)")


def cmd_drafts(a, conn):
    uid = user_id(conn, a.user)
    sql = """SELECT c.id, c.source, c.title, c.latest_chapter FROM comics c
             WHERE NOT EXISTS (SELECT 1 FROM user_tracking t WHERE t.comic_id=c.id AND t.user_id=?)"""
    args = [uid]
    if a.source:
        sql += " AND c.source=?"; args.append(a.source)
    if a.q:
        sql += " AND c.title LIKE ?"; args.append(f"%{a.q}%")
    sql += " ORDER BY c.updated_at DESC, c.id DESC LIMIT ?"; args.append(a.limit)
    rows = conn.execute(sql, args).fetchall()
    for r in rows:
        print(f"{r['id']:>6}  {r['source']:<10} ch.{r['latest_chapter'] or '-':<6} {r['title']}")
    print(f"-- {len(rows)} drafts shown")


def cmd_track(a, conn):
    uid = user_id(conn, a.user)
    for pk in a.comic_ids:
        row = comic_row(conn, pk)
        first = row["detail_fetched_at"] is None
        if first:
            print(f"[{pk}] first pick, fetching '{row['title']}' in full ...", flush=True)
        n = service.track(conn, make_source(row["source"], a.delay), uid, pk, notify=not a.no_notify)
        print(f"[{pk}] tracking '{row['title']}'" + (f" ({n} chapters stored)" if first else ""))


def cmd_untrack(a, conn):
    uid = user_id(conn, a.user)
    for pk in a.comic_ids:
        cur = conn.execute("DELETE FROM user_tracking WHERE user_id=? AND comic_id=?", (uid, pk))
        print(f"[{pk}] " + ("untracked" if cur.rowcount else "was not tracked"))
    conn.commit()


def cmd_tracked(a, conn):
    uid = user_id(conn, a.user)
    rows = conn.execute(
        """SELECT c.id, c.source, c.title, c.last_checked_at,
                  (SELECT MAX(number) FROM chapters WHERE comic_id=c.id) AS latest,
                  (SELECT COUNT(*) FROM chapters ch WHERE ch.comic_id=c.id AND ch.number >
                      COALESCE((SELECT number FROM chapters WHERE id=t.last_read_chapter_id), -1)) AS unread
           FROM user_tracking t JOIN comics c ON c.id=t.comic_id
           WHERE t.user_id=? ORDER BY unread DESC, c.title""", (uid,)).fetchall()
    for r in rows:
        print(f"{r['id']:>6}  {r['source']:<10} latest {r['latest'] or '-':<6} unread {r['unread']:<4} {r['title']}")
    print(f"-- {len(rows)} tracked")


def cmd_check(a, conn):
    names = [a.source] if a.source else [r["name"] for r in conn.execute("SELECT name FROM sources WHERE enabled=1")]
    total = 0
    for name in names:
        found = service.check_source(conn, make_source(name, a.delay))
        total += sum(len(v[1]) for v in found.values())
        for title, new in found.values():
            print(f"NEW  {name}: {title}: " + ", ".join(c.title or str(c.number) for c in new))
    print(f"-- {total} new chapters")


def cmd_read(a, conn):
    uid = user_id(conn, a.user)
    comic_row(conn, a.comic_id)
    ok = service.mark_read(conn, uid, a.comic_id, a.chapter)
    print("marked as read" if ok else "comic is not in your tracked list")


def cmd_log(a, conn):
    for r in conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (a.limit,)):
        print(f"{r['started_at']}  {r['source']:<10} {r['kind']:<8} comic={r['comic_id'] or '-':<6} "
              f"{'ok ' if r['ok'] else 'ERR'} new={r['new_chapters']} {r['error'] or ''}")


def cmd_run(a, conn):
    from apscheduler.schedulers.blocking import BlockingScheduler

    def job(name):
        with db.session(a.db) as c:  # one connection per run: jobs execute on worker threads
            service.check_source(c, make_source(name, a.delay))

    sched = BlockingScheduler()
    for r in conn.execute("SELECT name, check_interval_min FROM sources WHERE enabled=1"):
        minutes = a.interval or r["check_interval_min"]
        sched.add_job(job, "interval", minutes=minutes, args=[r["name"]], id=r["name"],
                      max_instances=1, coalesce=True, next_run_time=datetime.now())
        logging.info("scheduled %s every %s min", r["name"], minutes)
    conn.close()
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass


def cmd_serve(a, conn):
    import uvicorn

    from komik.api import create_app

    conn.close()
    app = create_app(a.db, scheduler=a.scheduler, default_user=a.user)
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", help=f"database path (default {db.DEFAULT_PATH}, or $KOMIK_DB)")
    p.add_argument("--user", default=db.DEFAULT_USER)
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests to a site")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)
    s = sub.add_parser("user-add"); s.add_argument("username"); s.add_argument("--email"); s.set_defaults(fn=cmd_user_add)
    s = sub.add_parser("sync-list"); s.add_argument("source", choices=SOURCES); s.add_argument("--pages", type=int, default=1); s.set_defaults(fn=cmd_sync_list)
    s = sub.add_parser("drafts"); s.add_argument("--source", choices=SOURCES); s.add_argument("--q"); s.add_argument("--limit", type=int, default=30); s.set_defaults(fn=cmd_drafts)
    s = sub.add_parser("track"); s.add_argument("comic_ids", type=int, nargs="+"); s.add_argument("--no-notify", action="store_true"); s.set_defaults(fn=cmd_track)
    s = sub.add_parser("untrack"); s.add_argument("comic_ids", type=int, nargs="+"); s.set_defaults(fn=cmd_untrack)
    sub.add_parser("tracked").set_defaults(fn=cmd_tracked)
    s = sub.add_parser("check"); s.add_argument("--source", choices=SOURCES); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("read"); s.add_argument("comic_id", type=int); s.add_argument("--chapter", type=float); s.set_defaults(fn=cmd_read)
    s = sub.add_parser("log"); s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_log)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000); s.add_argument("--scheduler", action="store_true", help="also run the update checker inside the server"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("run"); s.add_argument("--interval", type=int, help="override every source's interval (minutes)"); s.set_defaults(fn=cmd_run)

    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = db.connect(a.db)
    if a.cmd != "init":
        row = conn.execute("SELECT name FROM sqlite_master WHERE name='comics'").fetchone()
        if row is None:
            sys.exit("database is empty, run: python manage.py init")
    try:
        a.fn(a, conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
