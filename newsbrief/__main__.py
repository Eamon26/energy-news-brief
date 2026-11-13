"""CLI: python -m newsbrief [--hours 24] [--engine llm|rules] [--feeds config/feeds.json]"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .brief import render
from .classify import LLMClassifier, RuleClassifier
from .dedupe import dedupe
from .sources import collect, parse_feed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Daily AI brief of market-moving energy news")
    p.add_argument("--feeds", default="config/feeds.json")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--engine", choices=["llm", "rules"],
                   default="llm" if os.environ.get("ANTHROPIC_API_KEY") else "rules")
    p.add_argument("--offline", metavar="XML", nargs="+",
                   help="Parse local feed files instead of fetching (for demos/tests)")
    p.add_argument("--out", default="output")
    args = p.parse_args(argv)

    now = datetime.now(timezone.utc)
    print(f"Collecting headlines (last {args.hours:g}h)...")
    if args.offline:
        arts = []
        for f in args.offline:
            arts += parse_feed(Path(f).read_text(), Path(f).stem)
        hours = float("inf")
    else:
        arts = collect(args.feeds, hours=args.hours, now=now)
        hours = args.hours
    arts = dedupe(arts)
    print(f"{len(arts)} unique headlines; classifying with {args.engine}...")

    clf = LLMClassifier() if args.engine == "llm" else RuleClassifier()
    signals = clf.classify(arts)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    md = render(arts, signals, now, args.hours if hours != float("inf") else 0, args.engine)
    (out / f"brief-{stamp}.md").write_text(md)
    (out / f"signals-{stamp}.json").write_text(json.dumps(
        [{"title": arts[i].title, "source": arts[i].source, "link": arts[i].link, **s.to_dict()}
         for i, s in sorted(signals.items())], indent=2))
    print(f"Wrote {out / f'brief-{stamp}.md'} and signals-{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
