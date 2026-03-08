# Kottapalli

Static markdown export of [kottapalli.in](https://kottapalli.in/), a Telugu children's magazine.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL with the `kottapalli` database loaded locally

## Export

```bash
uv run python export.py
```

This reads from the local `kottapalli` PostgreSQL database and outputs:

- `content/` — Markdown files with YAML frontmatter, organized as `content/{year}/{month}/{slug}.md`
- `redirects.json` — Mapping of old redirect keys to target keys

## Output structure

```
content/
  _index.md                          # site root
  2008/
    _index.md                        # year section
    04/
      _index.md                      # issue page (ఏప్రిల్ 2008)
      prasa-kavitalu.md              # article
      somu-kotulu.md
      ...
```

Article filenames are Roman transliterations of the Telugu titles (e.g., ప్రాస కవితలు → `prasa-kavitalu.md`). The original key is preserved in each file's `key` frontmatter field.

## Build & Preview

```bash
# Build the static site
zola build

# Preview locally with live reload
zola serve
```

The built site goes to `public/`. Preview runs at `http://127.0.0.1:1111`.
