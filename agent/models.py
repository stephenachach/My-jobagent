"""Data models."""
from dataclasses import dataclass, field, asdict
import json


@dataclass
class Job:
    source: str                 # myjobmag / remotive / remoteok
    url: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    apply_url: str = ""
    apply_email: str = ""       # extracted email, if the post says "send CV to ..."
    posted_date: str = ""
    remote: bool = False
    salary: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @property
    def short_description(self) -> str:
        return (self.description or "")[:600]
