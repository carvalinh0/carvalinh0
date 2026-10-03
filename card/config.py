"""Load, validate and normalise config.yml."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# Every placeholder the generator knows how to fill.
KNOWN_PLACEHOLDERS = {
    "username", "name", "bio", "company", "location", "website", "email",
    "created", "age", "account_age",
    "followers", "following", "repos", "contributed", "stars", "forks",
    "gists", "prs", "issues", "contributions",
    "commits", "loc", "loc_add", "loc_del", "languages",
}
LOC_PLACEHOLDERS = {"commits", "loc", "loc_add", "loc_del"}
REPO_SCAN_PLACEHOLDERS = {
    "repos", "contributed", "stars", "forks", "languages",
} | LOC_PLACEHOLDERS

DEFAULTS: dict[str, Any] = {
    "username": "",
    "birthday": "",
    "language": "pt",
    "top_languages": 3,
    "thousands": ",",
    "offsets": {"commits": 0, "contributed": 0, "loc_add": 0, "loc_del": 0},
    "loc": {"max_commit_lines": 10000, "exclude_repos": []},
    "ascii": {
        "source": "avatar",
        "image": "",
        "file": "ascii.txt",
        "width": 38,
        "invert": False,
        "contrast": 1.4,
    },
    "theme": {
        "font_size": 16,
        "line_height": 20,
        "char_width": 9.6,
        "text_columns": 64,
        "rule": "—",
        "dark": {
            "background": "#161b22", "text": "#c9d1d9", "key": "#ffa657",
            "value": "#a5d6ff", "add": "#3fb950", "del": "#f85149",
            "dim": "#616e7f",
        },
        "light": {
            "background": "#f6f8fa", "text": "#24292f", "key": "#953800",
            "value": "#0a3069", "add": "#1a7f37", "del": "#cf222e",
            "dim": "#c2cfde",
        },
    },
    "sections": [],
}


class ConfigError(Exception):
    """Raised for problems in config.yml, with a message meant for the user."""


# Normalised content model
@dataclass
class Field:
    key: str
    value: str


@dataclass
class Row:
    fields: list[Field]


@dataclass
class Blank:
    pass


@dataclass
class Section:
    title: str
    items: list[Field | Row | Blank] = field(default_factory=list)


@dataclass
class Config:
    raw: dict[str, Any]
    sections: list[Section]

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def used_placeholders(self) -> set[str]:
        """Placeholders referenced anywhere in the card (to skip useless API calls)."""
        texts: list[str] = []
        for sec in self.sections:
            texts.append(sec.title)
            for item in sec.items:
                if isinstance(item, Field):
                    texts.append(item.value)
                elif isinstance(item, Row):
                    texts.extend(f.value for f in item.fields)
        return {m for t in texts for m in PLACEHOLDER_RE.findall(t)}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _parse_field(entry: dict, where: str) -> Field:
    if len(entry) != 1:
        raise ConfigError(
            f"{where}: each line should be an unique key (ex.: 'OS: Linux'), "
            f"but found {list(entry)}. Are quotation marks missing?"
        )
    ((key, value),) = entry.items()
    return Field(_text(key), _text(value))


def _parse_items(lines: Any, where: str) -> list[Field | Row | Blank]:
    if lines is None:
        return []
    if not isinstance(lines, list):
        raise ConfigError(f"{where}: 'lines' must be a list.")
    items: list[Field | Row | Blank] = []
    for i, entry in enumerate(lines, 1):
        here = f"{where}, linha {i}"
        if entry is None or entry == "":
            items.append(Blank())
        elif isinstance(entry, dict) and list(entry) == ["row"]:
            cols = entry["row"]
            if not isinstance(cols, list) or not cols:
                raise ConfigError(f"{here}: 'row' must have a list of columns.")
            fields = []
            for col in cols:
                if not isinstance(col, dict):
                    raise ConfigError(f"{here}: each column of 'row' must be 'Key: Value'.")
                fields.append(_parse_field(col, here))
            items.append(Row(fields))
        elif isinstance(entry, dict):
            items.append(_parse_field(entry, here))
        else:
            raise ConfigError(
                f"{here}: invalid format ({entry!r}). Use 'Key: Value', '\"\"' or 'row:'."
            )
    return items


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    try:
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML file in {path}:\n{exc}") from exc
    if not isinstance(user, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top.")

    raw = _deep_merge(DEFAULTS, user)
    raw["username"] = _text(raw["username"]).strip().lstrip("@")
    raw["birthday"] = _text(raw["birthday"]).strip()
    if raw["ascii"]["source"] not in {"avatar", "image", "file", "none"}:
        raise ConfigError("ascii.source must be: avatar, image, file or none.")
    loc = raw["loc"]
    try:
        loc["max_commit_lines"] = int(loc["max_commit_lines"])
    except (TypeError, ValueError):
        raise ConfigError("loc.max_commit_lines must be a number (0 = no limit).")
    if loc["exclude_repos"] is None:
        loc["exclude_repos"] = []
    if not isinstance(loc["exclude_repos"], list):
        raise ConfigError("loc.exclude_repos must be a list, ex.: [my-dataset, org/repo].")
    if raw["language"] not in {"pt", "en"}:
        raise ConfigError("language must be 'pt' or 'en'.")

    sections_raw = raw["sections"]
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ConfigError("Define at least one section in 'sections'.")
    sections = []
    for i, sec in enumerate(sections_raw, 1):
        if not isinstance(sec, dict):
            raise ConfigError(f"Section {i}: expects 'title' and 'lines'.")
        title = _text(sec.get("title"))
        sections.append(Section(title, _parse_items(sec.get("lines"), f"Section {i} ('{title}')")))
    return Config(raw=raw, sections=sections)
