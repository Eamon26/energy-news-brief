"""Turn headlines into structured market signals.

Two engines share one output schema:
- RuleClassifier: keyword rules, no network, deterministic (used in tests and as fallback).
- LLMClassifier: Claude via the Anthropic Messages API, forced into a JSON tool schema,
  validated, and backfilled by the rules for anything missing or malformed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, asdict

MARKETS = ("oil", "gas", "power", "carbon")
EVENT_TYPES = ("supply", "demand", "policy", "weather", "geopolitics", "price_move", "other")
DIRECTIONS = ("bullish", "bearish", "neutral")  # for the market's price

MARKET_WORDS = {
    "oil": ["oil", "crude", "brent", "wti", "opec", "barrel", "refinery", "diesel", "gasoline",
            "jet fuel", "tanker", "shale"],
    "gas": ["gas", "lng", "ttf", "nbp", "henry hub", "pipeline", "storage", "regasification"],
    "power": ["power", "electricity", "grid", "wind", "solar", "nuclear", "baseload", "interconnector",
              "megawatt", "mwh", "blackout", "outage", "national grid", "ofgem"],
    "carbon": ["carbon", "eua", "emissions", "ets", "allowance", "co2"],
}

BULLISH = ["cut", "cuts", "outage", "outages", "shutdown", "shut", "strike", "sanction", "sanctions",
           "attack", "attacks", "disruption", "disrupted", "cold snap", "freeze", "heatwave", "low wind",
           "draw", "drawdown", "shortage", "tight", "hurricane", "force majeure", "halt", "halts",
           "surge", "surges", "jumps", "rally", "rallies", "soar", "soars", "spike", "deficit"]
BEARISH = ["increase output", "raise output", "boost output", "output hike", "surplus", "glut",
           "build", "stockbuild", "mild", "weak demand", "demand slump", "ceasefire", "restart",
           "restarts", "resumes", "record wind", "oversupply", "falls", "fall", "drops", "drop",
           "slump", "slumps", "plunge", "plunges", "slide", "slides", "ease", "eases",
           "supply increase", "more supply", "weighs"]
EVENT_WORDS = {
    "weather": ["weather", "cold", "heatwave", "hurricane", "storm", "wind", "temperature", "drought"],
    "geopolitics": ["sanction", "war", "attack", "ceasefire", "russia", "ukraine", "iran", "israel",
                    "red sea", "houthi", "middle east", "tariff"],
    "policy": ["opec", "regulator", "ofgem", "mandate", "policy", "government", "eu ", "commission",
               "price cap", "subsidy", "auction", "ets"],
    "supply": ["output", "production", "outage", "shutdown", "maintenance", "refinery", "field",
               "pipeline", "lng", "restart", "strike", "force majeure", "exports", "imports"],
    "demand": ["demand", "consumption", "china", "economy", "recession", "imports surge"],
    "price_move": ["price", "prices", "rally", "falls", "jumps", "surge", "slump", "settles", "hits"],
}
EVENT_WEIGHT = {"supply": 3, "geopolitics": 3, "weather": 2, "policy": 2, "demand": 2,
                "price_move": 1, "other": 0}


@dataclass
class Signal:
    idx: int
    markets: list
    event_type: str
    direction: str
    importance: int          # 1 (minor) .. 3 (market-moving)
    why: str                 # one line: the mechanism
    watch: str               # one line: what to monitor next
    engine: str = "rules"

    def to_dict(self):
        return asdict(self)


def _has(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


class RuleClassifier:
    name = "rules"

    def classify_one(self, idx: int, title: str, summary: str = "", n_outlets: int = 1) -> Signal | None:
        text = f"{title} {summary}".lower()
        markets = [m for m, words in MARKET_WORDS.items() if any(_has(text, w) for w in words)]
        if not markets:
            return None
        head = title.lower()
        bull = sum(_has(head, w) for w in BULLISH)
        bear = sum(_has(head, w) for w in BEARISH)
        direction = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
        scores = {e: sum(_has(text, w) for w in words) for e, words in EVENT_WORDS.items()}
        event = max(scores, key=lambda e: (scores[e], EVENT_WEIGHT[e]))
        if scores[event] == 0:
            event = "other"
        raw = EVENT_WEIGHT[event] + (1 if direction != "neutral" else 0) + min(n_outlets - 1, 2)
        importance = 3 if raw >= 4 else 2 if raw >= 2 else 1
        why = f"{event.replace('_', ' ')} news, read as {direction} for {', '.join(markets)}"
        return Signal(idx, markets, event, direction, importance, why,
                      "Follow-up reports and the next settlement price", "rules")

    def classify(self, articles) -> dict[int, Signal]:
        out = {}
        for i, a in enumerate(articles):
            n = 1 + len(a.extra.get("also_reported_by", []))
            s = self.classify_one(i, a.title, a.summary, n)
            if s:
                out[i] = s
        return out


TOOL = {
    "name": "record_signals",
    "description": "Record a structured trading signal for each headline that is relevant to oil, gas, power or carbon prices. Omit irrelevant headlines.",
    "input_schema": {
        "type": "object",
        "properties": {"signals": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "idx": {"type": "integer", "description": "Index of the headline in the input list"},
                "markets": {"type": "array", "items": {"type": "string", "enum": list(MARKETS)}},
                "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
                "direction": {"type": "string", "enum": list(DIRECTIONS),
                              "description": "Likely short-term effect on the price of the main market"},
                "importance": {"type": "integer", "minimum": 1, "maximum": 3,
                               "description": "3 = could move prices today; 1 = background"},
                "why": {"type": "string", "description": "One sentence: the supply/demand mechanism"},
                "watch": {"type": "string", "description": "One sentence: what a trader should monitor next"},
            },
            "required": ["idx", "markets", "event_type", "direction", "importance", "why", "watch"],
        }}},
        "required": ["signals"],
    },
}

SYSTEM = (
    "You are an energy-markets analyst supporting a trading desk covering European and global oil, gas, "
    "power and carbon. For each headline, judge only what the headline and snippet state; do not invent "
    "figures. Direction refers to the likely short-term price effect on the main market affected. "
    "Be conservative: use 'neutral' and importance 1 when the effect is unclear."
)


class LLMClassifier:
    name = "llm"

    def __init__(self, api_key: str | None = None, model: str | None = None, batch: int = 25,
                 poster=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("NEWSBRIEF_MODEL", "claude-sonnet-5-5")
        self.batch = batch
        self.poster = poster or self._post
        self.fallback = RuleClassifier()

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _valid(s: dict, n: int) -> bool:
        return (isinstance(s.get("idx"), int) and 0 <= s["idx"] < n
                and s.get("markets") and all(m in MARKETS for m in s["markets"])
                and s.get("event_type") in EVENT_TYPES and s.get("direction") in DIRECTIONS
                and s.get("importance") in (1, 2, 3) and s.get("why") and s.get("watch"))

    def classify(self, articles) -> dict[int, Signal]:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; use --engine rules or set the key.")
        out: dict[int, Signal] = {}
        for start in range(0, len(articles), self.batch):
            chunk = articles[start:start + self.batch]
            listing = "\n".join(f"[{i}] {a.title} | {a.source} | {a.summary[:200]}" for i, a in enumerate(chunk))
            body = {"model": self.model, "max_tokens": 4000, "system": SYSTEM,
                    "tools": [TOOL], "tool_choice": {"type": "tool", "name": "record_signals"},
                    "messages": [{"role": "user", "content": f"Headlines:\n{listing}"}]}
            try:
                resp = self.poster(body)
                block = next(b for b in resp.get("content", []) if b.get("type") == "tool_use")
                for s in block["input"].get("signals", []):
                    if self._valid(s, len(chunk)):
                        g = start + s["idx"]
                        out[g] = Signal(g, s["markets"], s["event_type"], s["direction"],
                                        s["importance"], s["why"].strip(), s["watch"].strip(), "llm")
            except Exception as exc:  # network, schema or parsing failure → rules for this chunk
                print(f"  ! LLM batch {start}-{start + len(chunk)} failed ({exc}); using rules")
                for i, a in enumerate(chunk):
                    s = self.fallback.classify_one(start + i, a.title, a.summary)
                    if s:
                        out[start + i] = s
        return out
