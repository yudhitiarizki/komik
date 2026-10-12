"""Shinigami (11.shinigami.asia). The site is a SPA over a public JSON API at
api.shngm.io, so we call the API directly instead of parsing HTML."""
from ..http import Client
from ..models import Chapter, Comic
from .base import Source

STATUS = {1: "ongoing", 2: "completed", 3: "hiatus"}


def _names(taxonomy, key):
    return [t["name"] for t in taxonomy.get(key, [])]


class Shinigami(Source):
    name = "shinigami"
    image_headers = {"Referer": "https://11.shinigami.asia/"}

    def __init__(self, delay=1.0):
        self.api = Client(
            "https://api.shngm.io/v1",
            headers={"Accept": "application/json", "Referer": "https://11.shinigami.asia/"},
            delay=delay,
        )

    def _comic(self, d) -> Comic:
        tax = d.get("taxonomy") or {}
        return Comic(
            id=d["manga_id"],
            title=d["title"],
            source=self.name,
            description=d.get("description", ""),
            alt_titles=[t.strip() for t in (d.get("alternative_title") or "").split("|") if t.strip()],
            cover_url=d.get("cover_portrait_url") or d.get("cover_image_url") or "",
            status=STATUS.get(d.get("status"), str(d.get("status", ""))),
            year=d.get("release_year", ""),
            country=d.get("country_id", ""),
            authors=_names(tax, "Author"),
            genres=_names(tax, "Genre"),
            latest_chapter=d.get("latest_chapter_number"),
            updated_at=d.get("updated_at", ""),
        )

    def list_comics(self, page=1, page_size=24, **filters):
        params = {"page": page, "page_size": page_size, "sort": "latest", "sort_order": "desc", **filters}
        j = self.api.get_json("manga/list", params=params)
        return [self._comic(d) for d in j["data"]], j["meta"]["total_page"]

    def get_comic(self, comic_id):
        return self._comic(self.api.get_json(f"manga/detail/{comic_id}")["data"])

    def list_chapters(self, comic_id):
        chapters, page = [], 1
        while True:
            j = self.api.get_json(f"chapter/{comic_id}/list", params={"page": page, "page_size": 100})
            chapters += [
                Chapter(
                    id=d["chapter_id"],
                    comic_id=comic_id,
                    number=d["chapter_number"],
                    title=d.get("chapter_title", ""),
                    released_at=d.get("release_date") or d.get("created_at", ""),
                )
                for d in j["data"]
            ]
            if page >= j["meta"]["total_page"]:
                return sorted(chapters, key=lambda c: c.number)
            page += 1

    def chapter_images(self, chapter_id):
        d = self.api.get_json(f"chapter/detail/{chapter_id}")["data"]
        base, path = d["base_url"].rstrip("/"), d["chapter"]["path"]
        return [f"{base}{path}{name}" for name in d["chapter"]["data"]]
