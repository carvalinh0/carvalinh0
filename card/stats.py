"""Fetch GitHub data and turn it into the {placeholder} values."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from dateutil import relativedelta

from .config import Config, LOC_PLACEHOLDERS, REPO_SCAN_PLACEHOLDERS
from .github import GitHubClient, GitHubError
from .loc import cache_path, compute_loc, print_report

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    id login name bio company location websiteUrl email createdAt
    followers { totalCount }
    following { totalCount }
    gists { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection { contributionCalendar { totalContributions } }
  }
}
"""

AFFILIATIONS = ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"]


def _repos_query(page: int, with_loc: bool, with_langs: bool) -> str:
    extra = ""
    if with_loc:
        extra += "defaultBranchRef { target { ... on Commit { history { totalCount } } } }\n"
    if with_langs:
        extra += (
            "languages(first: 5, orderBy: {field: SIZE, direction: DESC}) "
            "{ edges { size node { name } } }\n"
        )
    return f"""
query($login: String!, $cursor: String, $aff: [RepositoryAffiliation]) {{
  user(login: $login) {{
    repositories(first: {page}, after: $cursor, ownerAffiliations: $aff) {{
      nodes {{
        nameWithOwner isFork stargazerCount forkCount
        owner {{ login }}
        {extra}
      }}
      pageInfo {{ hasNextPage endCursor }}
    }}
  }}
}}"""


def fetch_repos(client: GitHubClient, username: str, with_loc: bool, with_langs: bool) -> list[dict]:
    # Smaller pages when asking for heavy fields avoids 502 timeouts.
    page = 40 if (with_loc or with_langs) else 100
    query = _repos_query(page, with_loc, with_langs)
    nodes: list[dict] = []
    cursor = None
    while True:
        data = client.graphql(query, {"login": username, "cursor": cursor, "aff": AFFILIATIONS})
        conn = data["user"]["repositories"]
        nodes += [n for n in conn["nodes"] if n]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


def _top_languages(owned: list[dict], n: int) -> str:
    sizes: Counter[str] = Counter()
    for repo in owned:
        if repo.get("isFork"):
            continue
        for edge in (repo.get("languages") or {}).get("edges", []):
            sizes[edge["node"]["name"]] += edge["size"]
    return ", ".join(name for name, _ in sizes.most_common(n))


def collect(
    client: GitHubClient,
    username: str,
    cfg: Config,
    cache_dir: str | Path = "cache",
    log: Callable[[str], None] = print,
    report: bool = False,
) -> dict[str, Any]:
    """Raw (unformatted) values for every placeholder the card uses."""
    used = cfg.used_placeholders()
    data = client.graphql(PROFILE_QUERY, {"login": username})
    user = data.get("user")
    if not user:
        raise GitHubError(f"User '{username}' not found in GitHub.")

    raw: dict[str, Any] = {
        "username": user["login"],
        "name": user["name"] or user["login"],
        "bio": user["bio"] or "",
        "company": (user["company"] or "").lstrip("@"),
        "location": user["location"] or "",
        "website": (user["websiteUrl"] or "").removeprefix("https://").removeprefix("http://").rstrip("/"),
        "email": user["email"] or "",
        "created": user["createdAt"][:10],
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "gists": user["gists"]["totalCount"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributions": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "_created_at": dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00")),
    }

    if (used & REPO_SCAN_PLACEHOLDERS) or report:
        with_loc = bool(used & LOC_PLACEHOLDERS) or report
        with_langs = "languages" in used
        nodes = fetch_repos(client, user["login"], with_loc, with_langs)
        me = user["login"].lower()
        owned = [n for n in nodes if n["owner"]["login"].lower() == me]
        raw["repos"] = len(owned)
        raw["contributed"] = len(nodes)
        raw["stars"] = sum(n["stargazerCount"] for n in owned)
        raw["forks"] = sum(n["forkCount"] for n in owned)
        if with_langs:
            raw["languages"] = _top_languages(owned, int(cfg["top_languages"]))
        if with_loc:
            path = cache_path(cache_dir, user["login"])
            opts = cfg["loc"]
            raw.update(compute_loc(client, nodes, user["id"], path,
                                   opts["max_commit_lines"], opts["exclude_repos"], log))
            if report:
                print_report(nodes, path, opts["max_commit_lines"], log=log)

    off = cfg["offsets"]
    if "contributed" in raw:
        raw["contributed"] += int(off["contributed"])
    if "commits" in raw:
        raw["commits"] += int(off["commits"])
        raw["loc_add"] += int(off["loc_add"])
        raw["loc_del"] += int(off["loc_del"])
        raw["loc"] = raw["loc_add"] - raw["loc_del"]
    return raw


# Formatting
UNITS = {
    "pt": (("ano", "anos"), ("mês", "meses"), ("dia", "dias")),
    "en": (("year", "years"), ("month", "months"), ("day", "days")),
}


def format_age(start: dt.datetime, now: dt.datetime, language: str) -> str:
    diff = relativedelta.relativedelta(now, start)
    parts = []
    for value, (one, many) in zip((diff.years, diff.months, diff.days), UNITS[language]):
        parts.append(f"{value} {one if value == 1 else many}")
    text = ", ".join(parts)
    if diff.months == 0 and diff.days == 0:
        text += " 🎂"
    return text


def format_number(value: int, thousands: str) -> str:
    text = f"{value:,}"
    return text.replace(",", thousands) if thousands != "," else text


def build_values(raw: dict[str, Any], cfg: Config, now: dt.datetime | None = None) -> dict[str, str]:
    """Raw values -> display strings (every known placeholder gets an entry)."""
    now = now or dt.datetime.now()
    lang, sep = cfg["language"], cfg["thousands"]
    values: dict[str, str] = {}
    for key, val in raw.items():
        if key.startswith("_"):
            continue
        values[key] = format_number(val, sep) if isinstance(val, int) and not isinstance(val, bool) else str(val)
    if cfg["birthday"]:
        try:
            born = dt.datetime.strptime(cfg["birthday"], "%Y-%m-%d")
        except ValueError:
            from .config import ConfigError
            raise ConfigError("birthday must have the format AAAA-MM-DD (ex.: 2000-01-31).")
        values["age"] = format_age(born, now, lang)
    if "_created_at" in raw:
        values["account_age"] = format_age(raw["_created_at"].replace(tzinfo=None), now, lang)
    return values
