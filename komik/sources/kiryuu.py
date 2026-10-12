"""Kiryuu (v7.kiryuu.to). WordPress, server-rendered HTML with Tailwind markup.
robots.txt disallows /wp-json/, so we only parse the public HTML pages.
The domain rotates (v7, v8, ...), so it can be overridden via `site=`."""
import re

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Chapter, Comic
from .base import Source

STATUSES = {"ongoing": "ongoing", "completed": "completed", "hiatus": "hiatus", "on hold": "hiatus"}


def _soup(resp):
    return BeautifulSoup(resp.text, "lxml")


def _path(href):
    return re.sub(r"^https?://[^/]+", "", href.strip()).strip("/")


def _number(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else 0.0


class Kiryuu(Source):
    name = "kiryuu"

    def __init__(self, delay=1.0, site="https://v7.kiryuu.to"):
        self.site = site.rstrip("/")
        self.image_headers = {"Referer": self.site + "/"}
        self.http = Client(self.site, headers={"Referer": self.site + "/"}, delay=delay, timeout=90)

    def list_comics(self, page=1, page_size=0, **filters):
        # page size is fixed by the site; filters are passed as query params (e.g. order, genre[]).
        path = "/manga/" if page == 1 else f"/manga/page/{page}/"
        soup = _soup(self.http.get(path, params=filters))
        comics, seen = [], set()
        for img in soup.select("a[href*='/manga/'] img.wp-post-image"):
            cover_a = img.find_parent("a")
            slug = _path(cover_a["href"]).removeprefix("manga/")
            if "/" in slug or slug in seen:
                continue
            card = cover_a
            while card.parent and not card.select("a[href*='/chapter-']"):
                card = card.parent
            title = img.get("alt") or slug
            chapters = [a for a in card.select("a[href*='/chapter-']")]
            seen.add(slug)
            comics.append(
                Comic(
                    id=slug,
                    title=title,
                    source=self.name,
                    cover_url=img.get("src", ""),
                    latest_chapter=max((_number(a.get_text(" ", strip=True)) for a in chapters), default=None),
                    updated_at=re.sub(r"^Chapter\s*[\d.,]+\s*", "", chapters[0].get_text(" ", strip=True)) if chapters else "",
                )
            )
        # The pager only shows numbers around the current page, so the total is unknown;
        # report page + 1 while a link to the next page exists. Out-of-range pages
        # fall back to page 1 content, which has no such link.
        has_next = any(_path(a["href"]).endswith(f"manga/page/{page + 1}") for a in soup.select("a[href*='/manga/page/']"))
        return comics, page + 1 if has_next else page

    def get_comic(self, comic_id):
        soup = _soup(self.http.get(f"/manga/{comic_id}/"))
        info = {}
        for h4 in soup.select("h4"):
            spans = h4.select("span")
            val = h4.find_next_sibling("div")
            if spans and val and val.select_one("p"):
                info[spans[-1].get_text(strip=True)] = val.select_one("p").get_text(" ", strip=True)
        desc = soup.select_one("#tabpanel-description")
        cover = soup.select_one("meta[property='og:image']")
        m = re.search(r'"creativeWorkStatus":\s*"([^"]+)"', soup.decode())
        status = STATUSES.get(m.group(1).strip().lower(), m.group(1).strip().lower()) if m else ""
        h1 = soup.select_one("h1")
        chapters = self._parse_chapters(soup, comic_id)
        return Comic(
            id=comic_id,
            title=h1.get_text(" ", strip=True) if h1 else comic_id,
            source=self.name,
            description=re.sub(r"^Summary\s*", "", re.sub(r"\s+", " ", desc.get_text(" ", strip=True))) if desc else "",
            cover_url=cover["content"].replace("http://", "https://") if cover else "",
            status=status,
            year=info.get("Released", ""),
            genres=sorted({a.get_text(strip=True) for a in soup.select("a[href*='/genre/']") if a.get_text(strip=True)}),
            latest_chapter=max((c.number for c in chapters), default=None),
            updated_at=info.get("Last Updates", ""),
        )

    def _parse_chapters(self, soup, comic_id):
        chapters, seen = [], set()
        for row in soup.select("#chapter-list > div"):
            a = row.select_one("a[href*='/chapter-']")
            if not a:
                continue
            cid = _path(a["href"])
            if cid in seen:
                continue
            seen.add(cid)
            text = a.get_text(" | ", strip=True).split(" | ")
            number = float(row["data-chapter-number"]) if row.get("data-chapter-number") else _number(text[0])
            chapters.append(
                Chapter(
                    id=cid,
                    comic_id=comic_id,
                    number=number,
                    title=text[0],
                    released_at=text[1] if len(text) > 1 else "",
                )
            )
        return sorted(chapters, key=lambda c: c.number)

    def list_chapters(self, comic_id):
        return self._parse_chapters(_soup(self.http.get(f"/manga/{comic_id}/")), comic_id)

    def chapter_images(self, chapter_id):
        soup = _soup(self.http.get(f"/{chapter_id}/"))
        return [i["src"] for i in soup.select("div.kstorage-chapter img") if i.get("src")]
