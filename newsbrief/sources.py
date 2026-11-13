"""Fetch and parse RSS 2.0 / Atom feeds using only the standard library."""
from __future__ import annotations

import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "energy-news-brief/0.1 (+https://github.com/Eamon26)"


@dataclass
class Article:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str = ""
    feed: str = ""
    extra: dict = field(default_factory=dict)


def _clean(text: str | None) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, feed_name: str = "") -> list[Article]:
    """Parse an RSS or Atom document into Articles."""
    root = ET.fromstring(xml_text)
    out: list[Article] = []
    for item in root.iter("item"):  # RSS 2.0
        title = _clean(item.findtext("title"))
        source_el = item.find("source")
        source = _clean(source_el.text) if source_el is not None else feed_name
        # Google News appends " - Publisher" to titles; strip it when it matches the source.
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        out.append(Article(
            title=title,
            link=(item.findtext("link") or "").strip(),
            source=source,
            published=_parse_date(item.findtext("pubDate")),
            summary=_clean(item.findtext("description"))[:500],
            feed=feed_name,
        ))
    for entry in root.iter(f"{ATOM}entry"):  # Atom
        link_el = entry.find(f"{ATOM}link")
        out.append(Article(
            title=_clean(entry.findtext(f"{ATOM}title")),
            link=link_el.get("href", "") if link_el is not None else "",
            source=feed_name,
            published=_parse_date(entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")),
            summary=_clean(entry.findtext(f"{ATOM}summary"))[:500],
            feed=feed_name,
        ))
    return [a for a in out if a.title]


def fetch(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_feeds(config_path: str | Path) -> list[dict]:
    return json.loads(Path(config_path).read_text())["feeds"]


def collect(config_path: str | Path, hours: float = 24, now: datetime | None = None,
            fetcher=fetch, log=print) -> list[Article]:
    """Fetch every feed and keep articles from the last `hours` (undated ones are kept)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    articles: list[Article] = []
    for feed in load_feeds(config_path):
        try:
            items = parse_feed(fetcher(feed["url"]), feed["name"])
        except Exception as exc:  # one bad feed must not kill the brief
            log(f"  ! {feed['name']}: {exc}")
            continue
        fresh = [a for a in items if a.published is None or a.published >= cutoff]
        log(f"  {feed['name']}: {len(fresh)}/{len(items)} in window")
        articles.extend(fresh)
    return articles
