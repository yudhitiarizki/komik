from dataclasses import dataclass, field


@dataclass
class Comic:
    id: str
    title: str
    source: str
    description: str = ""
    alt_titles: list = field(default_factory=list)
    cover_url: str = ""
    status: str = ""
    year: str = ""
    country: str = ""
    authors: list = field(default_factory=list)
    genres: list = field(default_factory=list)
    latest_chapter: float | None = None
    updated_at: str = ""


@dataclass
class Chapter:
    id: str
    comic_id: str
    number: float
    title: str = ""
    released_at: str = ""
