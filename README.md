# Energy News Brief

A daily, AI-generated morning brief of market-moving energy news for a trading desk: it pulls headlines on **oil, gas, power and carbon** from free RSS feeds, removes syndicated duplicates, turns each headline into a structured signal (market, event type, likely price direction, importance, mechanism, what to watch) and writes a one-page brief plus a machine-readable JSON file.

It is a small version of the "AI workflows to scrape, summarise and structure unstructured market news" that energy trading desks now ask junior analysts to build.

## How it works

```
RSS / Atom feeds ──► parse + 24h window ──► de-duplicate ──► classify ──► brief.md + signals.json
 (config/feeds.json)   (stdlib only)        (title Jaccard)   │
                                                             ├─ LLM engine: Claude, forced into a JSON tool schema,
                                                             │  every field validated; failed batches fall back to rules
                                                             └─ Rules engine: keyword lexicons, deterministic, offline
```

- **No third-party dependencies.** Python 3.10+ standard library only, so it runs anywhere.
- **Structured, validated LLM output.** The model must call a `record_signals` tool whose schema restricts markets, event types and directions to fixed sets; anything out of range is dropped.
- **Fails safe.** A dead feed is skipped with a warning; an API error on a batch falls back to the rules engine for that batch, so a brief is always produced.
- **Tested.** 9 unit tests cover parsing, the time window, de-duplication, both classifiers (including malformed LLM output and API failure) and rendering.

## Run it

```bash
# Rules engine, no API key needed
python -m newsbrief --engine rules

# Claude engine (default when the key is set)
export ANTHROPIC_API_KEY=sk-ant-...
python -m newsbrief --hours 24
# optional: export NEWSBRIEF_MODEL=<model id>

# Offline demo on the bundled sample feed
python -m newsbrief --offline tests/fixtures/sample_feed.xml --engine rules

# Tests
python -m unittest discover -s tests -t .
```

Output lands in `output/brief-YYYY-MM-DD.md` and `output/signals-YYYY-MM-DD.json`. To run it every weekday at 07:00, add a cron line such as
`0 7 * * 1-5 cd /path/to/energy-news-brief && /usr/bin/python3 -m newsbrief`.

## Example output

See [`output/sample_brief.md`](output/sample_brief.md), generated from the bundled **illustrative** sample feed (the sample headlines are written for testing and are not real news).

## Results so far

- The rules engine classifies all 7 hand-labelled market headlines in the sample set with the correct market and direction, and ignores the irrelevant one. This is a small, synthetic test of the plumbing, not evidence of accuracy on real news.
- **Next:** label ~100 real headlines and compare the rules and Claude engines on market, direction and importance agreement; then check whether high-importance signals line up with next-day moves in Brent, TTF and UK day-ahead power.

## Limitations

- Headline-level only: it reads titles and feed snippets, not full articles.
- "Direction" is a first read of the likely short-term price effect, not a forecast and not trading advice.
- Google News feeds are a convenient free source but their coverage and ordering change over time.

## Layout

```
newsbrief/sources.py   fetch + parse RSS/Atom, time window
newsbrief/dedupe.py    near-duplicate headline collapse
newsbrief/classify.py  rules engine + Claude engine (tool schema, validation, fallback)
newsbrief/brief.py     Markdown brief and per-market read-across
config/feeds.json      feed list (edit freely)
tests/                 unit tests + illustrative sample feed
```
