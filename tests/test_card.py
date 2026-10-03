import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from card.ascii_art import image_to_ascii
from card.config import ConfigError, load_config
from card.loc import cache_path
from card.render import build_lines, parse_segments, render_svg, seg_len, substitute
from card.stats import build_values, collect, format_age, format_number

ROOT = Path(__file__).resolve().parent.parent


def write_cfg(tmp_path, body: str):
    p = tmp_path / "config.yml"
    p.write_text(body, encoding="utf-8")
    return load_config(p)


# config
def test_default_config_loads():
    cfg = load_config(ROOT / "config.yml")
    assert cfg.sections and "repos" in cfg.used_placeholders()


def test_bad_line_gives_friendly_error(tmp_path):
    with pytest.raises(ConfigError, match="única chave"):
        write_cfg(tmp_path, "sections:\n  - title: x\n    lines:\n      - {A: 1, B: 2}\n")


def test_invalid_ascii_source(tmp_path):
    with pytest.raises(ConfigError, match="ascii.source"):
        write_cfg(tmp_path, "ascii: {source: nope}\nsections:\n  - title: x\n    lines: []\n")


# rendering
def test_segments_and_substitution():
    segs = parse_segments("{a} <add>{b}++</add> x")
    assert [s for _, s in segs] == ["value", "add", "value"]
    warns = []
    out = substitute(segs, {"a": "1", "b": "2"}, warns.append)
    assert "".join(t for t, _ in out) == "1 2++ x" and not warns
    substitute(parse_segments("{nope}"), {}, warns.append)
    assert warns


def test_all_lines_have_same_width_and_empty_fields_hidden(tmp_path):
    cfg = write_cfg(tmp_path, """
theme: {text_columns: 50}
sections:
  - title: "{username}@github"
    lines:
      - Nome: "{name}"
      - Empresa: "{company}"
      - Idade: "{age}"
      - row:
          - A: "{repos}"
          - B: "{stars}"
          - C: "{followers}"
""")
    values = {"username": "u", "name": "Fulano", "company": "", "repos": "1",
              "stars": "22", "followers": "333"}
    lines = build_lines(cfg, values)
    texts = ["".join(t for t, _ in l) for l in lines]
    assert not any("Empresa" in t or "Idade" in t for t in texts)
    assert {len(t) for t in texts} == {50}


def test_long_value_is_truncated(tmp_path):
    cfg = write_cfg(tmp_path, 'theme: {text_columns: 30}\nsections:\n  - title: ""\n    lines:\n      - Bio: "{bio}"\n')
    lines = build_lines(cfg, {"bio": "x" * 200})
    assert seg_len(lines[0]) <= 30 and lines[0][-1][0] == "…"


def test_svg_is_valid_xml_and_escapes_ascii():
    from xml.etree import ElementTree as ET
    cfg = load_config(ROOT / "config.yml")
    lines = build_lines(cfg, {"username": "u"}, warn=lambda m: None)
    svg = render_svg(lines, ["<&>", " \\ "], cfg["theme"], cfg["theme"]["dark"])
    ET.fromstring(svg.split("\n", 1)[1])  # skip the XML declaration


# stats helpers
def test_number_and_age_formatting():
    import datetime as dt
    assert format_number(1234567, ".") == "1.234.567"
    assert format_number(1234567, ",") == "1,234,567"
    assert format_age(dt.datetime(2000, 1, 1), dt.datetime(2002, 2, 2), "pt") == "2 anos, 1 mês, 1 dia"
    assert format_age(dt.datetime(2000, 1, 1), dt.datetime(2002, 3, 5), "en") == "2 years, 2 months, 4 days"


# ascii
def test_image_to_ascii_handles_light_and_dark_backgrounds():
    def png(bg, fg):
        img = Image.new("RGB", (100, 100), bg)
        ImageDraw.Draw(img).ellipse((25, 25, 75, 75), fill=fg)
        buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()

    for data in (png("white", "black"), png("black", "white")):
        art = image_to_ascii(data, 30, 0.48)
        assert len(art) == 14
        # background is blank, the disc is dense -> centre has ink, corners don't
        assert art[0][:3].strip() == "" and art[7][15] != " "


# collect() with a fake API
class FakeClient:
    def __init__(self):
        self.calls = 0
        self.loc_queries = []
        self.totals = {"me/a": 10, "me/b": 5, "org/c": 7}
        self.extra = {"b": [{"additions": 900_000, "deletions": 5, "parents": {"totalCount": 2}},   # merge
                            {"additions": 4_000_000, "deletions": 0, "parents": {"totalCount": 1}}]}  # dataset dump

    def graphql(self, query, variables=None):
        self.calls += 1
        if "contributionsCollection" in query:
            return {"user": {
                "id": "U1", "login": "me", "name": None, "bio": None, "company": "@acme",
                "location": None, "websiteUrl": "https://me.dev/", "email": "",
                "createdAt": "2020-01-01T00:00:00Z",
                "followers": {"totalCount": 3}, "following": {"totalCount": 4},
                "gists": {"totalCount": 0}, "pullRequests": {"totalCount": 5},
                "issues": {"totalCount": 6},
                "contributionsCollection": {"contributionCalendar": {"totalContributions": 99}}}}
        if "repositories(" in query:
            def node(full, stars, fork=False):
                owner = full.split("/")[0]
                return {"nameWithOwner": full, "isFork": fork, "stargazerCount": stars,
                        "forkCount": 1, "owner": {"login": owner},
                        "languages": {"edges": [{"size": 100, "node": {"name": "Python"}}]},
                        "defaultBranchRef": {"target": {"history": {"totalCount": self.totals[full]}}}}
            return {"user": {"repositories": {
                "nodes": [node("me/a", 2), node("me/b", 3), node("org/c", 50)],
                "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        if "history(first: 100" in query:
            self.loc_queries.append(variables["name"])
            nodes = [{"additions": 10, "deletions": 4, "parents": {"totalCount": 1}},
                     {"additions": 5, "deletions": 1, "parents": {"totalCount": 1}}]
            nodes += self.extra.get(variables["name"], [])
            return {"repository": {"defaultBranchRef": {"target": {"history": {
                "totalCount": len(nodes), "nodes": nodes,
                "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
        raise AssertionError(query)


CFG = """
offsets: {commits: 100, contributed: 1, loc_add: 1000, loc_del: 0}
sections:
  - title: t
    lines:
      - X: "{repos} {contributed} {stars} {commits} {loc} {languages} {company} {website}"
"""


def test_collect_counts_and_incremental_cache(tmp_path):
    cfg = write_cfg(tmp_path, CFG)
    client = FakeClient()
    raw = collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert (raw["repos"], raw["contributed"], raw["stars"]) == (2, 3 + 1, 5)  # org/c not owned; +1 offset
    # commits: a=2, b=4 (merge and giant still count as commits), c=2  (+100 offset)
    assert raw["commits"] == 8 + 100
    # lines: merge and 4M-line commit are ignored -> 15 per repo x3 (+1000 offset)
    assert raw["loc_add"] == 45 + 1000 and raw["loc_del"] == 15
    assert raw["languages"] == "Python" and raw["company"] == "acme" and raw["website"] == "me.dev"
    assert sorted(client.loc_queries) == ["a", "b", "c"]

    # second run: nothing changed -> no per-repo queries
    client.loc_queries.clear()
    collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert client.loc_queries == []

    # one repo got new commits -> only that one is recomputed
    client.totals["me/b"] = 6
    collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert client.loc_queries == ["b"]

    # cache never stores readable repo names
    text = cache_path(tmp_path / "cache", "me").read_text()
    assert "me/a" not in text and json.loads(text)["version"]


def test_unused_placeholders_skip_expensive_queries(tmp_path):
    cfg = write_cfg(tmp_path, 'sections:\n  - title: t\n    lines:\n      - F: "{followers}"\n')
    client = FakeClient()
    raw = collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert client.calls == 1 and raw["followers"] == 3 and "repos" not in raw
    assert build_values(raw, cfg)["followers"] == "3"


def test_exclude_repos_and_cache_invalidation_on_new_limit(tmp_path):
    cfg = write_cfg(tmp_path, CFG + "loc:\n  exclude_repos: [ORG/c, a]\n")
    client = FakeClient()
    raw = collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert sorted(client.loc_queries) == ["b"]               # a and org/c skipped (case-insensitive)
    assert raw["commits"] == 4 + 100 and raw["loc_add"] == 15 + 1000

    # same settings -> cached
    client.loc_queries.clear()
    collect(client, "me", cfg, tmp_path / "cache", log=lambda m: None)
    assert client.loc_queries == []

    # no limit -> cache built with another limit must be discarded; giant commit now counts
    cfg2 = write_cfg(tmp_path, CFG + "loc:\n  max_commit_lines: 0\n  exclude_repos: [ORG/c, a]\n")
    raw2 = collect(client, "me", cfg2, tmp_path / "cache", log=lambda m: None)
    assert client.loc_queries == ["b"] and raw2["loc_add"] == 15 + 4_000_000 + 1000


def test_loc_report_prints_names_only_when_asked(tmp_path):
    cfg = write_cfg(tmp_path, CFG)
    out = []
    collect(FakeClient(), "me", cfg, tmp_path / "cache", log=out.append, report=True)
    text = "\n".join(out)
    assert "me/b" in text and "gigantes" in text
    quiet = []
    collect(FakeClient(), "me", cfg, tmp_path / "cache2", log=quiet.append)
    assert "me/b" not in "\n".join(quiet)
