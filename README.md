# komik

Scrapers for several comic sites plus a small tracker that stores comics in SQLite
and checks the ones you picked for new chapters.

```
pip install -r requirements.txt
```

## Scraping only (no database): `cli.py`
```
python cli.py <source> list|comic|chapters|images|dump|download ...
```
Sources: `shinigami`, `komiku`, `komikindo`, `kiryuu`. Add a site by writing a
`komik/sources/<name>.py` that implements `Source` and registering it in `komik/sources/__init__.py`.

## Tracker: `manage.py`
```
python manage.py init                          # create data/komik.db + default user "local"
python manage.py sync-list komiku --pages 3    # fill the draft list for a source
python manage.py drafts --source komiku --q ao # browse drafts (ids are database ids)
python manage.py track 12                      # pick a comic; first pick fetches all chapters
python manage.py tracked                       # your comics + unread counts
python manage.py check [--source komiku]       # one update check now
python manage.py run [--interval 10]           # scheduler, per-source interval (sources.check_interval_min)
python manage.py read 12 [--chapter 40]        # mark as read
python manage.py log                           # sync history
python manage.py --user budi track 12          # other users share the same comic data
```
## Web UI + API
```
python manage.py serve [--scheduler] [--port 8000]   # http://127.0.0.1:8000
```
`--scheduler` also runs the update checker inside the server (per-source intervals).
The server binds to localhost only and has no login: do not expose it to the internet as is.

| Endpoint | |
|---|---|
| `GET /api/sources` | sources + comic / tracked counts |
| `GET /api/comics?scope=drafts\|tracked\|all&source=&q=&limit=&offset=` | list (tracked ones include `unread`) |
| `GET /api/comics/{id}` | detail + chapters (with `read` flag) |
| `POST /api/comics/{id}/track` / `DELETE` | pick / drop (first pick fetches every chapter) |
| `POST /api/comics/{id}/read?upto=N` | mark read up to chapter number N (default: latest) |
| `GET /api/chapters/{id}/images` | live image URLs for the reader |
| `POST /api/sources/{name}/sync?pages=N` | refresh the draft list |
| `POST /api/check?source=` | check tracked comics for new chapters now |
| `GET /api/log` | sync history |

All comic endpoints accept `?user=<name>` (default `local`). Interactive docs at `/docs`.

Database path: `data/komik.db` or `$KOMIK_DB` / `--db`.

Design notes
- A comic is a *draft* until its detail has been fetched (`detail_fetched_at IS NULL`).
  Whoever tracks it first triggers the full fetch; later users just link to it.
- The scheduler checks each tracked comic once no matter how many users track it.
- Sources may implement `quick_latest()` for a one-request check (Shinigami does);
  others fall back to re-reading the chapter list.
- Be polite: requests are rate limited per site (`--delay`, default 1s).
