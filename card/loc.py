"""Lines-of-code / commit totals, cached per repository.

Only repositories whose commit count changed since the last run are
re-queried, so daily runs are cheap. Repository names are stored as
SHA-256 hashes so private repo names never end up in the public cache.

What is *not* counted as "your" lines:
  * merge commits (GitHub diffs them against the first parent, so a
    ``git pull`` would credit you with other people's work);
  * commits larger than ``max_commit_lines`` (datasets, lockfiles,
    vendored folders, generated code...).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from .github import GitHubClient

CACHE_VERSION = 3

REPO_LOC_QUERY = """
query($owner: String!, $name: String!, $uid: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $uid}) {
            totalCount
            nodes { additions deletions parents { totalCount } }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
  }
}
"""

ZERO = {"total": 0, "mine": 0, "add": 0, "del": 0, "merges": 0, "big": 0, "big_lines": 0}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_path(directory: str | Path, username: str) -> Path:
    return Path(directory) / f"{sha(username.lower())[:16]}.json"


def load_cache(path: Path, params: dict) -> dict[str, dict[str, int]]:
    """Cached repos, or {} if the file is missing/old or was built with other settings."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if data.get("version") != CACHE_VERSION or data.get("params") != params:
        return {}
    return data.get("repos", {})


def save_cache(path: Path, repos: dict[str, dict[str, int]], params: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": CACHE_VERSION, "params": params, "repos": dict(sorted(repos.items()))}
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def is_excluded(full_name: str, exclude: Iterable[str]) -> bool:
    """Match 'owner/name' or just 'name', case-insensitive."""
    ex = {e.strip().lower() for e in exclude if e and e.strip()}
    low = full_name.lower()
    return low in ex or low.split("/", 1)[-1] in ex


def repo_loc(client: GitHubClient, owner: str, name: str, user_id: str, max_lines: int) -> dict[str, int]:
    """Per-repo numbers for the user's commits on the default branch."""
    out = {"mine": 0, "add": 0, "del": 0, "merges": 0, "big": 0, "big_lines": 0}
    cursor = None
    while True:
        data = client.graphql(
            REPO_LOC_QUERY,
            {"owner": owner, "name": name, "uid": user_id, "cursor": cursor},
        )
        ref = (data.get("repository") or {}).get("defaultBranchRef")
        if not ref:
            return out
        history = ref["target"]["history"]
        out["mine"] = history["totalCount"]
        for node in history["nodes"]:
            add, dele = node["additions"], node["deletions"]
            if node["parents"]["totalCount"] > 1:
                out["merges"] += 1
            elif max_lines and add + dele > max_lines:
                out["big"] += 1
                out["big_lines"] += add + dele
            else:
                out["add"] += add
                out["del"] += dele
        if not history["pageInfo"]["hasNextPage"]:
            return out
        cursor = history["pageInfo"]["endCursor"]


def compute_loc(
    client: GitHubClient,
    repos: list[dict[str, Any]],
    user_id: str,
    path: Path,
    max_lines: int = 10_000,
    exclude: Iterable[str] = (),
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Totals across ``repos`` (nodes from the repositories query)."""
    params = {"max_commit_lines": int(max_lines)}
    old = load_cache(path, params)
    fresh: dict[str, dict[str, int]] = {}
    updated = 0
    try:
        for node in repos:
            full = node["nameWithOwner"]
            if is_excluded(full, exclude):
                continue
            key = sha(full)
            ref = node.get("defaultBranchRef")
            if not ref or not ref.get("target"):  # empty repository
                fresh[key] = dict(ZERO)
                continue
            total = ref["target"]["history"]["totalCount"]
            cached = old.get(key)
            if cached and cached.get("total") == total:
                fresh[key] = cached
                continue
            owner, name = full.split("/", 1)
            fresh[key] = {"total": total, **repo_loc(client, owner, name, user_id, int(max_lines))}
            updated += 1
        save_cache(path, fresh, params)  # prunes repos that no longer exist/renamed
    except BaseException:
        # Keep everything computed so far, plus the old entries, so the
        # next run resumes instead of starting over.
        save_cache(path, {**old, **fresh}, params)
        raise
    merges = sum(r.get("merges", 0) for r in fresh.values())
    big = sum(r.get("big", 0) for r in fresh.values())
    big_lines = sum(r.get("big_lines", 0) for r in fresh.values())
    log(f"   LOC: {updated} recalculated repositories, {len(fresh) - updated} within cache")
    log(f"   ignored: {merges} merges and {big} massive commits ({big_lines:,} lines)")
    return {
        "commits": sum(r["mine"] for r in fresh.values()),
        "loc_add": sum(r["add"] for r in fresh.values()),
        "loc_del": sum(r["del"] for r in fresh.values()),
    }


def print_report(repos: list[dict[str, Any]], path: Path, max_lines: int, top: int = 15,
                 log: Callable[[str], None] = print) -> None:
    """Show which repositories weigh most (prints real repo names: use locally only)."""
    cache = load_cache(path, {"max_commit_lines": int(max_lines)})
    rows = []
    for node in repos:
        entry = cache.get(sha(node["nameWithOwner"]))
        if entry:
            rows.append((entry["add"] + entry["del"], node["nameWithOwner"], entry))
    rows.sort(reverse=True)
    log(f"\n   Top {min(top, len(rows))} repositories by counted lines (limit: {max_lines:,}):")
    log(f"   {'repositório':<38}{'commits':>8}{'+linhas':>11}{'-linhas':>11}{'merges':>8}{'gigantes':>10}")
    for _, name, e in rows[:top]:
        big = f"{e.get('big', 0)} ({e.get('big_lines', 0):,})" if e.get("big") else "0"
        log(f"   {name[:37]:<38}{e['mine']:>8}{e['add']:>11,}{e['del']:>11,}{e.get('merges', 0):>8}{big:>10}")
    log("   Hint: Still finding a massive repo? Place it inside loc.exclude_repos or reduce loc.max_commit_lines.\n")
