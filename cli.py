#!/usr/bin/env python3
"""Usage:
  python cli.py shinigami list [--page N] [--size N]
  python cli.py shinigami comic <comic_id>
  python cli.py shinigami chapters <comic_id>
  python cli.py shinigami images <chapter_id>
  python cli.py shinigami dump --out data/shinigami.json [--limit N]
  python cli.py shinigami download <chapter_id> [--out downloads]
"""
import argparse
import json
import os
from dataclasses import asdict

from komik.sources import SOURCES


def dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=lambda o: asdict(o)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", choices=SOURCES)
    p.add_argument("cmd", choices=["list", "comic", "chapters", "images", "dump", "download"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=24)
    p.add_argument("--limit", type=int)
    p.add_argument("--out")
    p.add_argument("--delay", type=float, default=1.0)
    a = p.parse_args()
    src = SOURCES[a.source](delay=a.delay)

    if a.cmd == "list":
        comics, total = src.list_comics(a.page, a.size)
        dump({"total_pages": total, "comics": comics})
    elif a.cmd == "comic":
        dump(src.get_comic(a.arg))
    elif a.cmd == "chapters":
        dump(src.list_chapters(a.arg))
    elif a.cmd == "images":
        dump(src.chapter_images(a.arg))
    elif a.cmd == "dump":
        out = a.out or f"data/{a.source}.json"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        rows = []
        for i, c in enumerate(src.iter_all_comics(a.size)):
            if a.limit and i >= a.limit:
                break
            row = asdict(c)
            row["chapters"] = [asdict(ch) for ch in src.list_chapters(c.id)]
            rows.append(row)
            print(f"[{i + 1}] {c.title} ({len(row['chapters'])} ch)", flush=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"saved {len(rows)} comics -> {out}")
    elif a.cmd == "download":
        folder = os.path.join(a.out or "downloads", a.source, a.arg)
        os.makedirs(folder, exist_ok=True)
        for n, url in enumerate(src.chapter_images(a.arg), 1):
            ext = os.path.splitext(url)[1] or ".jpg"
            path = os.path.join(folder, f"{n:03d}{ext}")
            if os.path.exists(path):
                continue
            r = src.api.get(url, headers=src.image_headers)
            with open(path, "wb") as f:
                f.write(r.content)
            print(path)


if __name__ == "__main__":
    main()
