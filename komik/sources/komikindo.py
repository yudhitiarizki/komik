"""KomikIndo (komikindo.ch). WordPress theme, server-rendered HTML.
robots.txt disallows /wp-json/, so we only parse the public HTML pages."""
import re

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Chapter, Comic
from .base import Source

SITE = "https://komikindo.ch"
STATUS = {"berjalan": "ongoing", "tamat": "completed"}


def _soup(resp):
    return BeautifulSoup(resp.text, "lxml")


def _slug(href, prefix=""):
    path = re.sub(r"^https?://[^/]+", "", href)
    return path.split(prefix, 1)[-1].strip("/") if prefix else path.strip("/")


def _number(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _split(text):
    return [t.strip() for t in text.split(",") if t.strip()]


class KomikIndo(Source):
    name = "komikindo"
    image_headers = {"Referer": SITE + "/"}

    def __init__(self, delay=1.0):
        self.http = Client(SITE, headers={"Referer": SITE + "/"}, delay=delay)

    def list_comics(self, page=1, page_size=0, **_):
        # page size is fixed by the site; the argument is ignored.
        path = "/komik-terbaru/" if page == 1 else f"/komik-terbaru/page/{page}/"
        soup = _soup(self.http.get(path))
        comics = []
        for card in soup.select("div.animposx"):
            a = card.select_one(".tt a[href*='/komik/']")
            if not a:
                continue
            img = card.select_one("img")
            flag = card.select_one(".typeflag")
            last = card.select_one(".lsch a")
            date = card.select_one(".datech")
            comics.append(
                Comic(
                    id=_slug(a["href"], "/komik/"),
                    title=a.get_text(strip=True),
                    source=self.name,
                    cover_url=img.get("src", "") if img else "",
                    genres=[flag["class"][-1]] if flag and len(flag.get("class", [])) > 1 else [],
                    latest_chapter=_number(last.get_text()) if last else None,
                    updated_at=date.get_text(strip=True) if date else "",
                )
            )
        pages = [int(n.get_text(strip=True)) for n in soup.select("a.page-numbers") if n.get_text(strip=True).isdigit()]
        return comics, max(pages + [page])

    def get_comic(self, comic_id):
        soup = _soup(self.http.get(f"/komik/{comic_id}/"))
        info = {}
        for span in soup.select(".infox .spe > span"):
            b = span.find("b")
            if b:
                info[b.get_text(strip=True).rstrip(":")] = span.get_text(" ", strip=True).split(":", 1)[-1].strip()
        title = soup.select_one("h1.entry-title")
        cover = soup.select_one("meta[property='og:image']")
        desc = soup.select_one(".entry-content-single")
        chapters = self._parse_chapters(soup, comic_id)
        return Comic(
            id=comic_id,
            title=re.sub(r"^Komik\s+", "", title.get_text(" ", strip=True)) if title else comic_id,
            source=self.name,
            description=re.sub(r"\s+", " ", desc.get_text(" ", strip=True)) if desc else "",
            alt_titles=_split(info.get("Judul Alternatif", "")),
            cover_url=cover["content"] if cover else "",
            status=STATUS.get(info.get("Status", "").lower(), info.get("Status", "").lower()),
            authors=_split(info.get("Pengarang", "")),
            genres=[a.get_text(strip=True) for a in soup.select("a[href*='/genres/'][rel='tag']")],
            latest_chapter=max((c.number for c in chapters), default=None),
        )

    def _parse_chapters(self, soup, comic_id):
        chapters = []
        for li in soup.select("#chapter_list li"):
            a = li.select_one(".lchx a")
            if not a:
                continue
            date = li.select_one(".dt a")
            chapters.append(
                Chapter(
                    id=_slug(a["href"]),
                    comic_id=comic_id,
                    number=_number(a.get_text(" ", strip=True)),
                    title=a.get_text(" ", strip=True),
                    released_at=date.get_text(strip=True) if date else "",
                )
            )
        return sorted(chapters, key=lambda c: c.number)

    def list_chapters(self, comic_id):
        return self._parse_chapters(_soup(self.http.get(f"/komik/{comic_id}/")), comic_id)

    def chapter_images(self, chapter_id):
        soup = _soup(self.http.get(f"/{chapter_id}/"))
        return [img["src"] for img in soup.select("#chimg-auh img") if img.get("src")]
