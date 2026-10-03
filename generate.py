#!/usr/bin/env python3
"""Gera assets/dark.svg e assets/light.svg a partir do config.yml.

Uso:
    python generate.py            # dados reais (precisa de GH_TOKEN)
    python generate.py --demo     # dados fictícios, sem token nem internet
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
    "name": "Pessoa Exemplo", "bio": "Dev apaixonado por código aberto",
    "company": "ACME", "location": "São Paulo, Brasil",
    "website": "exemplo.dev", "email": "oi@exemplo.dev",
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
        "Não sei qual é o seu username. Preencha 'username' no config.yml "
        "ou use --username SEU_USUARIO."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yml", help="caminho do config (padrão: config.yml)")
    ap.add_argument("--username", help="sobrescreve o username do config")
    ap.add_argument("--demo", action="store_true", help="usa dados fictícios (sem token/internet)")
    ap.add_argument("--loc-report", action="store_true",
                    help="mostra quais repositórios mais pesam nas linhas de código (use só local: imprime nomes)")
    ap.add_argument("--out", help="pasta de saída (padrão: assets, ou preview com --demo)")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        base = Path(args.config).resolve().parent
        username = resolve_username(args.username, cfg["username"]) if not args.demo else (
            args.username or cfg["username"] or "octocat")
        print(f"Gerando card para @{username}" + (" (modo demo)" if args.demo else ""))

        if args.demo:
            raw = {**DEMO_STATS, "username": username,
                   "loc": DEMO_STATS["loc_add"] - DEMO_STATS["loc_del"],
                   "_created_at": dt.datetime(2018, 4, 12)}
        else:
            client = GitHubClient(find_token())
            raw = collect(client, username, cfg, base / "cache", report=args.loc_report)
            username = raw["username"]
            print(f"   chamadas à API: {client.calls}")

        values = build_values(raw, cfg)
        theme = cfg["theme"]
        aspect = float(theme["char_width"]) / float(theme["line_height"])
        art = load_ascii(cfg["ascii"], username, aspect, base, allow_network=not args.demo)
        lines = build_lines(cfg, values, warn=lambda m: print(f"   aviso: {m}"))

        out = Path(args.out or ("preview" if args.demo else base / "assets"))
        out.mkdir(parents=True, exist_ok=True)
        for mode in ("dark", "light"):
            svg = render_svg(lines, art, theme, theme[mode])
            (out / f"{mode}.svg").write_text(svg, encoding="utf-8")
            print(f"   escrito: {out / f'{mode}.svg'}")
    except (ConfigError, GitHubError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
