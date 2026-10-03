"""Minimal GitHub GraphQL client with retries and readable errors."""
from __future__ import annotations

import os
import time
from typing import Any

import requests

API_URL = "https://api.github.com/graphql"
RETRY_STATUS = {502, 503, 504}


class GitHubError(Exception):
    """Raised for API problems, with a message meant for the user."""


def find_token() -> str:
    for name in ("GH_TOKEN", "ACCESS_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(name, "").strip()
        if token:
            return token
    raise GitHubError(
        "No TOKEN found. Define GH_TOKEN (or ACCESS_TOKEN / GITHUB_TOKEN) "
        "in environment. In GitHub Actions, this is already handled by "
        "the workflow."
    )


class GitHubClient:
    def __init__(self, token: str, session: requests.Session | None = None, retries: int = 4):
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.retries = retries
        self.calls = 0

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        last = ""
        for attempt in range(self.retries):
            self.calls += 1
            try:
                resp = self.session.post(API_URL, json=payload, timeout=60)
            except requests.RequestException as exc:
                last = str(exc)
            else:
                if resp.status_code == 401:
                    raise GitHubError("Expired or invalid token (HTTP 401).")
                if resp.status_code in RETRY_STATUS or (
                    resp.status_code == 403 and "abuse" in resp.text.lower()
                ):
                    last = f"HTTP {resp.status_code}"
                elif resp.status_code != 200:
                    raise GitHubError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                else:
                    body = resp.json()
                    if body.get("errors") and not body.get("data"):
                        msg = "; ".join(e.get("message", "?") for e in body["errors"])
                        raise GitHubError(f"Error from GraphQL API: {msg}")
                    return body["data"]
            time.sleep(2 * (attempt + 1))
        raise GitHubError(f"The API failed after {self.retries} attempts ({last}).")
