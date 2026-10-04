#!/usr/bin/env python3
"""Generates assets/dark.svg and assets/light.svg from config.yml.

Usage:
    python generate.py            # real data (requires GH_TOKEN)
    python generate.py --demo     # mock data, no token or internet required
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from card.ascii_art import load_ascii
from card.config import ConfigError, load_config
from card.github import GitHubClient, GitHubError, find_token
from card.render import build_lines, render_svg
from card.stats import build_values, collect

DEMO_STATS = {
    "name": "Example Person", "bio": "Dev passionate about open source",
    "company": "ACME", "location": "São Paulo, Brazil",
    "website": "example.dev", "email": "hi@example.dev",
    "created": "2018-04-12", "followers": 1234, "following": 87,
    "repos": 42, "contributed": 58, "stars": 2310, "forks": 164,
    "gists": 9, "prs": 310, "issues": 128, "contributions": 1876,
    "commits": 9641, "loc_add": 523178, "loc_del": 76902,
    "languages": "TypeScript, Python, Rust",
}


def resolve_username(cli: str | None, configured: str) -> str:
    for candidate in (cli, configured, os.environ.get("USER_NAME"),
                      os.environ.get("GITHUB_REPOSITORY_OWNER")):
        if candidate and candidate.strip():
            return candidate.strip().lstrip("@")
    raise ConfigError(
        "Could not determine your username. Set 'username' in config.yml "
        "or use --username YOUR_USERNAME."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yml", help="config file path (default: config.yml)")
    ap.add_argument("--username", help="overrides the username in config")
    ap.add_argument("--demo", action="store_true", help="uses mock data (no token/internet needed)")
    ap.add_argument("--loc-report", action="store_true",
                    help="shows which repositories contribute the most to lines of code (use locally only: prints repository names)")
    ap.add_argument("--out", help="output directory (default: assets, or preview with --demo)")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        base = Path(args.config).resolve().parent
        username = resolve_username(args.username, cfg["username"]) if not args.demo else (
            args.username or cfg["username"] or "octocat")
        print(f"Generating card for @{username}" + (" (demo mode)" if args.demo else ""))

        if args.demo:
            raw = {**DEMO_STATS, "username": username,
                   "loc": DEMO_STATS["loc_add"] - DEMO_STATS["loc_del"],
                   "_created_at": dt.datetime(2018, 4, 12)}
        else:
            client = GitHubClient(find_token())
            raw = collect(client, username, cfg, base / "cache", report=args.loc_report)
            username = raw["username"]
            print(f"   API calls made: {client.calls}")

        values = build_values(raw, cfg)
        theme = cfg["theme"]
        aspect = float(theme["char_width"]) / float(theme["line_height"])
        art = load_ascii(cfg["ascii"], username, aspect, base, allow_network=not args.demo)
        lines = build_lines(cfg, values, warn=lambda m: print(f"   warning: {m}"))

        out = Path(args.out or ("preview" if args.demo else base / "assets"))
        out.mkdir(parents=True, exist_ok=True)
        for mode in ("dark", "light"):
            svg = render_svg(lines, art, theme, theme[mode])
            (out / f"{mode}.svg").write_text(svg, encoding="utf-8")
            print(f"   written: {out / f'{mode}.svg'}")
    except (ConfigError, GitHubError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())