from dataclasses import asdict, dataclass, fields


@dataclass
class NewsItem:
    id: str
    url: str
    title: str
    summary: str = ""
    source: str = ""
    published: str = ""

    importance: int = 0
    league: str = ""
    event: str = ""

    title_ru: str = ""
    summary_ru: str = ""
    category: str = ""
    image_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})
