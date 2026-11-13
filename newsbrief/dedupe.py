"""Collapse near-duplicate headlines (the same story syndicated by several outlets)."""
from __future__ import annotations

import re

STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with",
        "is", "are", "after", "amid", "over", "from", "its", "it", "be", "will", "says"}


def tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9$%.]+", title.lower())
    return {w.strip(".") for w in words if w not in STOP and len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe(articles, threshold: float = 0.6):
    """Keep the first article of each cluster of similar titles; record the other sources."""
    kept, kept_tokens = [], []
    for art in articles:
        t = tokens(art.title)
        match = next((i for i, kt in enumerate(kept_tokens) if jaccard(t, kt) >= threshold), None)
        if match is None:
            kept.append(art)
            kept_tokens.append(t)
        else:
            kept[match].extra.setdefault("also_reported_by", []).append(art.source)
    return kept
