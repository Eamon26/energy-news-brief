"""Render classified signals into a one-page Markdown morning brief."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

ARROW = {"bullish": "▲", "bearish": "▼", "neutral": "•"}
ORDER = ("oil", "gas", "power", "carbon")


def market_bias(signals) -> dict[str, str]:
    """Net direction per market, weighting each signal by its importance."""
    score = Counter()
    for s in signals:
        w = {"bullish": 1, "bearish": -1, "neutral": 0}[s.direction] * s.importance
        for m in s.markets:
            score[m] += w
    return {m: ("bullish" if score[m] > 1 else "bearish" if score[m] < -1 else "mixed")
            for m in ORDER if any(m in s.markets for s in signals)}


def render(articles, signals: dict, generated: datetime, hours: float, engine: str) -> str:
    sigs = sorted(signals.values(), key=lambda s: (-s.importance, s.idx))
    lines = [f"# Energy markets brief, {generated:%a %d %b %Y %H:%M} UTC",
             "",
             (f"{len(articles)} unique headlines in the last {hours:g}h; " if hours else f"{len(articles)} unique headlines (offline sample); ") + f"{len(sigs)} relevant to prices. "
             f"Engine: {engine}.",
             ""]
    if not sigs:
        return "\n".join(lines + ["No market-relevant headlines in this window."]) + "\n"

    bias = market_bias(sigs)
    lines += ["## Read across", "", "| Market | Net read | Signals |", "| --- | --- | --- |"]
    for m, b in bias.items():
        n = sum(m in s.markets for s in sigs)
        lines.append(f"| {m.title()} | {b} | {n} |")
    lines.append("")

    top = [s for s in sigs if s.importance == 3][:5] or sigs[:3]
    lines += ["## Top movers", ""]
    for s in top:
        a = articles[s.idx]
        lines += [f"**{ARROW[s.direction]} {a.title}** ([{a.source}]({a.link}))",
                  f"- Why: {s.why}", f"- Watch: {s.watch}", ""]

    for m in ORDER:
        rest = [s for s in sigs if m in s.markets and s not in top]
        if not rest:
            continue
        lines += [f"## {m.title()}", ""]
        for s in rest[:8]:
            a = articles[s.idx]
            also = a.extra.get("also_reported_by", [])
            more = f", +{len(also)} outlets" if also else ""
            lines.append(f"- {ARROW[s.direction]} [{a.title}]({a.link}) ({a.source}{more}): {s.why}")
        lines.append("")

    lines += ["---", "_Automated summary of public headlines; directions are a first read, not trade advice._"]
    return "\n".join(lines) + "\n"
