import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from newsbrief.brief import market_bias, render
from newsbrief.classify import LLMClassifier, RuleClassifier
from newsbrief.dedupe import dedupe
from newsbrief.sources import collect, parse_feed

FIX = Path(__file__).parent / "fixtures" / "sample_feed.xml"
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)

# Hand-labelled expectations for the sample headlines: (title start, market, direction)
LABELS = [
    ("Norwegian gas field outage", "gas", "bullish"),
    ("OPEC+ agrees to raise output", "oil", "bearish"),
    ("Brent crude jumps", "oil", "bullish"),
    ("Mild weather forecast", "gas", "bearish"),
    ("Low wind and nuclear outage", "power", "bullish"),
    ("EU carbon allowances slide", "carbon", "bearish"),
    ("Libyan oilfield restarts", "oil", "bearish"),
]


def sample(window=True):
    feeds = FIX.parent / "feeds_fixture.json"
    feeds.write_text(json.dumps({"feeds": [{"name": "sample", "url": "fixture"}]}))
    arts = collect(feeds, hours=24, now=NOW, fetcher=lambda url: FIX.read_text(), log=lambda *_: None) \
        if window else parse_feed(FIX.read_text(), "sample")
    feeds.unlink()
    return arts


class TestSources(unittest.TestCase):
    def test_parse_strips_publisher_suffix_and_reads_dates(self):
        arts = parse_feed(FIX.read_text(), "sample")
        self.assertEqual(len(arts), 10)
        self.assertEqual(arts[0].title, "Norwegian gas field outage cuts flows to UK")
        self.assertEqual(arts[0].source, "Sample Wire")
        self.assertEqual(arts[0].published, datetime(2026, 10, 26, 7, 10, tzinfo=timezone.utc))

    def test_time_window_drops_old_items(self):
        titles = [a.title for a in sample()]
        self.assertNotIn("Old story about LNG terminal opening", titles)
        self.assertEqual(len(titles), 9)

    def test_bad_feed_does_not_crash(self):
        feeds = FIX.parent / "bad.json"
        feeds.write_text(json.dumps({"feeds": [{"name": "broken", "url": "x"}]}))
        def boom(url):
            raise OSError("network down")
        self.assertEqual(collect(feeds, now=NOW, fetcher=boom, log=lambda *_: None), [])
        feeds.unlink()


class TestDedupe(unittest.TestCase):
    def test_syndicated_story_collapses(self):
        arts = dedupe(sample())
        self.assertEqual(len(arts), 8)
        self.assertEqual(arts[0].extra["also_reported_by"], ["Other Wire"])


class TestRules(unittest.TestCase):
    def test_labelled_accuracy(self):
        arts = dedupe(sample())
        sigs = RuleClassifier().classify(arts)
        by_title = {arts[i].title: s for i, s in sigs.items()}
        hits = 0
        for start, market, direction in LABELS:
            s = next(v for t, v in by_title.items() if t.startswith(start))
            hits += (market in s.markets and s.direction == direction)
        self.assertEqual(hits, len(LABELS))

    def test_irrelevant_headline_ignored(self):
        arts = dedupe(sample())
        sigs = RuleClassifier().classify(arts)
        self.assertFalse(any("Football" in arts[i].title for i in sigs))


class TestLLM(unittest.TestCase):
    def fake(self, signals):
        return lambda body: {"content": [{"type": "tool_use", "name": "record_signals",
                                          "input": {"signals": signals}}]}

    def test_valid_output_used_and_invalid_dropped(self):
        arts = dedupe(sample())
        good = {"idx": 0, "markets": ["gas"], "event_type": "supply", "direction": "bullish",
                "importance": 3, "why": "Lower Norwegian flows tighten UK supply.", "watch": "Restart date."}
        bad = {"idx": 99, "markets": ["gold"], "event_type": "x", "direction": "up",
               "importance": 7, "why": "", "watch": ""}
        clf = LLMClassifier(api_key="test", poster=self.fake([good, bad]))
        sigs = clf.classify(arts)
        self.assertEqual(list(sigs), [0])
        self.assertEqual(sigs[0].engine, "llm")

    def test_api_failure_falls_back_to_rules(self):
        def down(body):
            raise OSError("timeout")
        arts = dedupe(sample())
        sigs = LLMClassifier(api_key="test", poster=down).classify(arts)
        self.assertTrue(sigs)
        self.assertTrue(all(s.engine == "rules" for s in sigs.values()))


class TestBrief(unittest.TestCase):
    def test_render_contains_sections(self):
        arts = dedupe(sample())
        sigs = RuleClassifier().classify(arts)
        md = render(arts, sigs, NOW, 24, "rules")
        for part in ("# Energy markets brief", "## Read across", "## Top movers"):
            self.assertIn(part, md)
        self.assertIn(market_bias(list(sigs.values()))["oil"], ("bullish", "bearish", "mixed"))


if __name__ == "__main__":
    unittest.main()
