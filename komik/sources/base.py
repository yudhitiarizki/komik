from abc import ABC, abstractmethod
from typing import Iterator

from ..models import Chapter, Comic


class Source(ABC):
    """Interface every site scraper implements."""

    name: str

    @abstractmethod
    def list_comics(self, page: int = 1, page_size: int = 24) -> tuple[list[Comic], int]:
        """Return (comics, total_pages)."""

    @abstractmethod
    def get_comic(self, comic_id: str) -> Comic: ...

    @abstractmethod
    def list_chapters(self, comic_id: str) -> list[Chapter]: ...

    @abstractmethod
    def chapter_images(self, chapter_id: str) -> list[str]:
        """Return absolute image URLs in reading order."""

    def quick_latest(self, comic_id: str) -> float | None:
        """Cheap check: latest chapter number in one small request, or None if
        the site offers no such shortcut (callers then fall back to list_chapters)."""
        return None

    # Image hosts may require headers (e.g. Referer); override if needed.
    image_headers: dict = {}

    def iter_all_comics(self, page_size: int = 24) -> Iterator[Comic]:
        page = 1
        while True:
            comics, total = self.list_comics(page, page_size)
            yield from comics
            if page >= total:
                return
            page += 1
