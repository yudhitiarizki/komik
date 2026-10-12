"""Komiku (komiku.org). Server-rendered HTML, so we parse it with BeautifulSoup.
The comic list is an HTMX fragment served from api.komiku.org."""
import re

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Chapter, Comic
from .base import Source

SITE = "https://komiku.org"
LIST_API = "https://api.komiku.org/manga"


def _soup(resp):
    return BeautifulSoup(resp.text, "lxml")


def _number(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*$", text.strip())
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _slug(href, prefix=""):
    return href.split(prefix, 1)[-1].strip("/") if prefix else href.strip("/")


class Komiku(Source):
    name = "komiku"
    image_headers = {"Referer": SITE + "/"}

    def __init__(self, delay=1.0):
        self.http = Client(SITE, headers={"Referer": SITE + "/"}, delay=delay)

    def list_comics(self, page=1, page_size=10, **filters):
        # page_size is fixed by the site (10 per page); filters: orderby, tipe, genre, ...
        params = {"orderby": "date", **filters}
        url = f"{LIST_API}/" if page == 1 else f"{LIST_API}/page/{page}/"
        soup = _soup(self.http.get(url, params=params))
        comics = []
        for card in soup.select("div.bge"):
            a = card.select_one("div.kan a[href*='/manga/']")
            if not a:
                continue
            latest = card.select(".new1 a")
            kind = card.select_one(".tpe1_inf b")
            img = card.select_one("img")
            comics.append(
                Comic(
                    id=_slug(a["href"], "/manga/"),
                    title=a.get_text(strip=True),
                    source=self.name,
                    description=(card.select_one("div.kan p") or soup.new_tag("p")).get_text(strip=True),
                    cover_url=img.get("src", "") if img else "",
                    genres=[kind.get_text(strip=True)] if kind else [],
                    latest_chapter=_number(latest[-1].get_text()) if latest else None,
                    updated_at=(card.select_one(".judul2") or soup.new_tag("s")).get_text(" ", strip=True),
                )
            )
        has_next = soup.select_one("span[hx-get*='/page/']") is not None
        return comics, page + 1 if has_next else page

    def get_comic(self, comic_id):
        soup = _soup(self.http.get(f"/manga/{comic_id}/"))
        info = {}
        for tr in soup.select("table.inftable tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                info[tds[0].get_text(strip=True).rstrip(":")] = tds[1]
        text = lambda k: info[k].get_text(" ", strip=True) if k in info else ""  # noqa: E731
        cover = soup.select_one("meta[property='og:image']")
        desc = soup.select_one("p.desc")
        chapters = self._parse_chapters(soup, comic_id)
        return Comic(
            id=comic_id,
            title=text("Judul"),
            source=self.name,
            description=desc.get_text("\n", strip=True) if desc else "",
            alt_titles=[t.strip() for t in text("Judul Alternatif").split(",") if t.strip()],
            cover_url=cover["content"] if cover else "",
            status=text("Status").lower(),
            authors=[a.strip() for a in text("Author").split(",") if a.strip()],
            genres=[li.get_text(strip=True) for li in info["Genre"].select("li")] if "Genre" in info else [],
            latest_chapter=max((c.number for c in chapters), default=None),
        )

    def _parse_chapters(self, soup, comic_id):
        chapters = []
        for tr in soup.select("#daftarChapter tr"):
            a = tr.select_one("td.judulseries a")
            if not a:
                continue
            date = tr.select_one("td.tanggalseries")
            chapters.append(
                Chapter(
                    id=_slug(a["href"]),
                    comic_id=comic_id,
                    number=_number(a.get_text(strip=True)),
                    title=a.get_text(strip=True),
                    released_at=date.get_text(strip=True) if date else "",
                )
            )
        return sorted(chapters, key=lambda c: c.number)

    def list_chapters(self, comic_id):
        return self._parse_chapters(_soup(self.http.get(f"/manga/{comic_id}/")), comic_id)

    def chapter_images(self, chapter_id):
        soup = _soup(self.http.get(f"/{chapter_id}/"))
        return [img["src"] for img in soup.select("#Baca_Komik img.klazy") if img.get("src")]
