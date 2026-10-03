# Guide — GitHub Profile Card (neofetch style)

Generates two SVGs (`assets/dark.svg` and `assets/light.svg`) with your ASCII art
and GitHub statistics, updated daily via GitHub Actions.
Inspired by the profile [Andrew6rant](https://github.com/Andrew6rant/Andrew6rant),
but **everything is configured in a single file: `config.yml`**.

## Getting Started in 3 Steps

1. **Create your profile repository**: a *public* repository with the exact same
   name as your username (`YOUR_USERNAME/YOUR_USERNAME`) and push these files to it
   (or use "Use this template" / fork and rename).
2. **Adjust `config.yml`** (see details below). The `username` field can be left empty:
   it will automatically use the repository owner.
3. In the **Actions** tab, manually run **"Update profile card"** (*Run workflow*).
   After that, it runs automatically every day and upon every edit to `config.yml`.

> If Actions fails to push: *Settings -> Actions -> General -> Workflow permissions -> Read and write permissions*.

### Token (optional)

Without any extra configuration, the workflow uses the default `GITHUB_TOKEN` and only sees
**public** data. To include **private** and organization repository statistics:

1. Create a *Personal access token (classic)* with the `repo` and `read:user` scopes.
2. Save it under *Settings -> Secrets and variables -> Actions* named `ACCESS_TOKEN`.

## Editing the Card

Everything is managed inside `config.yml`, fully commented. Key concepts:

```yaml
sections:
  - title: "{username}@github"      # section title
    lines:
      - Name: "{name}"              # Key: value
      - IDE: "VS Code"              # free text
      - Languages.Top: "{languages}" # the "." separates colored parts
      - ""                          # blank line
      - row:                        # multiple columns on the same line
          - Repos: "{repos}"
          - Stars: "{stars}"
```

* **Lines with empty values automatically disappear** (e.g., if you don't have a company listed, the "Company" line will not show). Very long values are truncated with `…`.
* **Quotes**: values containing `{ }`, `:` or `#` must be enclosed in quotes.
* **Text colors**: `<add>…</add>` (green), `<del>…</del>` (red), `<key>`, `<value>`, `<dim>`.

### Available Placeholders

| Group | Placeholders |
|---|---|
| Profile | `{username}` `{name}` `{bio}` `{company}` `{location}` `{website}` `{email}` `{created}` |
| Time | `{age}` (requires `birthday` in config) · `{account_age}` |
| Numbers | `{followers}` `{following}` `{repos}` `{contributed}` `{stars}` `{forks}` `{gists}` `{prs}` `{issues}` `{contributions}` |
| Code | `{commits}` `{loc}` `{loc_add}` `{loc_del}` `{languages}` |

Only the data you actively use is fetched — if `{commits}`/`{loc}` are absent from the card, the lines of code calculation will not execute.

### ASCII Art

`ascii.source` supports:

| Value | Description |
|---|---|
| `avatar` | converts your GitHub profile picture automatically (default) |
| `image` | converts another image specified by path or URL in `ascii.image` |
| `file` | uses pre-made text from a file (`ascii.txt`) |
| `none` | text only, no ASCII art |

If the resulting ASCII looks inverted, set `invert: true`; adjust `width` and `contrast` until satisfied. If conversion fails, it falls back gracefully to `ascii.txt`.

### Deleted Repositories

Commits and lines of code from deleted repositories no longer exist in the GitHub API.
You can manually add them using `offsets:` in the config.

## Local Testing

```bash
pip install -r requirements.txt
python generate.py --demo # dummy data without token -> generates preview/ folder
GH_TOKEN=ghp_xxx python generate.py --username YOUR_USERNAME # real data
python -m pytest # run unit tests
```

Open `preview/dark.svg` in your browser to inspect the output.

## How Lines of Code (LOC) Calculation Works

For each repository, the script calculates lines added/deleted **within commits authored by you** on the default branch. Two things are **excluded** to prevent inflated numbers:

* **Merge commits** — GitHub calculates diffs against the first parent, so a `git pull` fetching other people's work could falsely credit you (or cause negative balances);
* **Huge commits** (`loc.max_commit_lines`, default 10,000 lines) — datasets, `package-lock.json`, `node_modules`, generated code.

Ignored commits still count towards `{commits}`. The calculation results are cached in `cache/*.json` (hashed repository names to protect private repo names). Only repos with new commits are recalculated. The first run might take longer; if a timeout/502 error occurs, re-run it—it resumes where it left off.

### Numbers Still Unusually High? Inspect Repository Weight

```bash
GH_TOKEN=ghp_xxx python generate.py --loc-report
```

Shows the top contributing repositories alongside ignored merges and massive commits per repo. If a specific repository dominates, add it to `loc.exclude_repos` or adjust `loc.max_commit_lines`.
(Run this locally only: the report prints repository names, including private ones.)

## Troubleshooting

* **Broken image on profile before first run** — the repo includes a demo card by default; trigger the workflow manually once.
* **Dark/light mode not toggling** — the README relies on `#gh-dark-mode-only` / `#gh-light-mode-only`. Alternatively, use absolute URLs in `<picture>` tags (`https://raw.githubusercontent.com/USERNAME/USERNAME/main/assets/dark.svg`).
* **Lower numbers than expected** — without an `ACCESS_TOKEN`, private repositories are excluded. Commits under email addresses not associated with your GitHub account will not be credited by the API.
* **Misaligned text on specific fonts** — fine-tune `theme.char_width` (default `9.6`) and/or `theme.text_columns`.