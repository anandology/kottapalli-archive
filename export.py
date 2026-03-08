"""Export kottapalli Infogami database to Zola-compatible markdown files."""

import json
import os
import re
import unicodedata

import psycopg2
import yaml

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

OUTPUT_DIR = "content"
STATIC_DIR = "static"
DB_NAME = "kottapalli"


def slugify(text):
    """Transliterate Telugu to ASCII roman slug."""
    roman = transliterate(text, sanscript.TELUGU, sanscript.ITRANS)
    # Strip diacritics
    nfkd = unicodedata.normalize("NFKD", roman)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = ascii_str.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def find_image(year, month, basename):
    """Find an image file with any common extension, return its URL path or None."""
    for ext in [".jpg", ".JPG", ".gif", ".GIF", ".png", ".PNG"]:
        path = os.path.join(STATIC_DIR, "images", year, month, basename + ext)
        if os.path.exists(path):
            return f"/images/{year}/{month}/{basename}{ext}"
    return None


def fetch_all(cur, type_key):
    """Fetch latest revision JSON for all things of a given type."""
    cur.execute(
        """
        SELECT d.data::jsonb
        FROM data d
        JOIN thing t ON d.thing_id = t.id
        JOIN thing tt ON t.type = tt.id
        WHERE tt.key = %s
          AND d.revision = t.latest_revision
        """,
        (type_key,),
    )
    return [row[0] for row in cur.fetchall()]


def build_frontmatter(article, issue_names, category_names):
    """Build YAML frontmatter dict for an article."""
    fm = {}
    fm["title"] = article.get("title", "")

    created = article.get("created", {}).get("value", "")
    if created:
        fm["date"] = created.split(".")[0]  # drop microseconds

    modified = article.get("last_modified", {}).get("value", "")
    if modified:
        fm["updated"] = modified.split(".")[0]

    fm["key"] = article.get("key", "")

    # Taxonomies
    taxonomies = {}
    cat_raw = article.get("category", {})
    if isinstance(cat_raw, str):
        cat_key = cat_raw
    else:
        cat_key = cat_raw.get("key", "")
    if cat_key:
        cat_name = category_names.get(cat_key, cat_key.split("/")[-1])
        taxonomies["category"] = [cat_name]

    issue_raw = article.get("issue", {})
    if isinstance(issue_raw, str):
        issue_key = issue_raw
    else:
        issue_key = issue_raw.get("key", "")
    if issue_key:
        # e.g. "/2008/04" -> "2008-04"
        taxonomies["issue"] = [issue_key.strip("/").replace("/", "-")]

    if taxonomies:
        fm["taxonomies"] = taxonomies

    # Extra
    extra = {}
    if issue_key:
        issue_name = issue_names.get(issue_key, "")
        if issue_name:
            extra["issue_name"] = issue_name

    intro_raw = article.get("intro", "")
    if isinstance(intro_raw, dict):
        intro_text = intro_raw.get("value", "")
    elif isinstance(intro_raw, str):
        intro_text = intro_raw
    else:
        intro_text = ""
    intro_text = intro_text.replace("\r\n", "\n").strip()
    if intro_text:
        extra["intro"] = intro_text

    if extra:
        fm["extra"] = extra

    return fm


def write_markdown(path, frontmatter, body):
    """Write a markdown file with YAML frontmatter."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(
            frontmatter,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        f.write("---\n\n")
        if body:
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")


def count_articles_per_issue(cur):
    """Count non-redirect articles per issue key."""
    cur.execute("""
        SELECT d.data::jsonb->'issue'->>'key' as issue_key, count(*)
        FROM data d
        JOIN thing t ON d.thing_id = t.id
        JOIN thing tt ON t.type = tt.id
        WHERE tt.key = '/type/article'
          AND d.revision = t.latest_revision
          AND NOT d.data::jsonb ? 'redirect'
          AND d.data::jsonb->'issue'->>'key' IS NOT NULL
        GROUP BY issue_key
        UNION
        SELECT d.data::jsonb->>'issue' as issue_key, count(*)
        FROM data d
        JOIN thing t ON d.thing_id = t.id
        JOIN thing tt ON t.type = tt.id
        WHERE tt.key = '/type/article'
          AND d.revision = t.latest_revision
          AND NOT d.data::jsonb ? 'redirect'
          AND jsonb_typeof(d.data::jsonb->'issue') = 'string'
        GROUP BY issue_key
    """)
    return {row[0]: row[1] for row in cur.fetchall()}


def export_articles(cur, issue_names, category_names):
    """Export all non-redirect articles to markdown files."""
    articles = fetch_all(cur, "/type/article")

    # Track slugs per directory to handle duplicates
    used_slugs = {}
    redirects = {}
    exported = 0
    skipped_redirects = 0

    for article in articles:
        # Skip redirects
        if "redirect" in article:
            redirect_target = article["redirect"]
            if isinstance(redirect_target, dict):
                redirect_target = redirect_target.get("key", "")
            redirects[article.get("key", "")] = redirect_target
            skipped_redirects += 1
            continue

        key = article.get("key", "")
        # Parse year/month/slug from key like "/2008/04/ప్రాస_కవితలు"
        parts = key.strip("/").split("/", 2)
        if len(parts) < 3:
            print(f"  SKIP (bad key): {key}")
            continue

        year, month, title_part = parts
        slug = slugify(title_part.replace("_", " "))
        if not slug:
            slug = "untitled"

        # Handle duplicate slugs
        dir_key = f"{year}/{month}"
        if dir_key not in used_slugs:
            used_slugs[dir_key] = {}
        if slug in used_slugs[dir_key]:
            used_slugs[dir_key][slug] += 1
            slug = f"{slug}-{used_slugs[dir_key][slug]}"
        else:
            used_slugs[dir_key][slug] = 1

        # Build content
        fm = build_frontmatter(article, issue_names, category_names)
        body_obj = article.get("body", "")
        if isinstance(body_obj, dict):
            body = body_obj.get("value", "")
        elif isinstance(body_obj, str):
            body = body_obj
        else:
            body = ""
        body = body.replace("\r\n", "\n")

        path = os.path.join(OUTPUT_DIR, year, month, f"{slug}.md")
        write_markdown(path, fm, body)
        exported += 1

    print(f"Exported {exported} articles, skipped {skipped_redirects} redirects")

    # Write redirects mapping
    with open("redirects.json", "w", encoding="utf-8") as f:
        json.dump(redirects, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(redirects)} redirects to redirects.json")


def export_sections(cur, issue_names, article_counts):
    """Generate _index.md for root, year, and year/month sections."""
    # Collect all year/month pairs from issues
    issues = fetch_all(cur, "/type/issue")
    years = set()

    # Track the latest published issue with content for root extra
    latest_published = None  # (year, month) tuple

    for issue in issues:
        key = issue.get("key", "")
        key_stripped = key.strip("/")
        parts = key_stripped.split("/")
        if len(parts) != 2:
            continue
        year, month = parts
        years.add(year)

        name = issue.get("name", f"{month}/{year}")
        published = issue.get("published", True)
        has_content = article_counts.get(key, 0) > 0
        created = issue.get("created", {}).get("value", "")

        # weight = YYYYMM so sections sort chronologically
        weight = int(year) * 100 + int(month)
        fm = {"title": name, "sort_by": "date", "weight": weight}
        is_published = published and has_content
        extra = {"published": is_published}
        if is_published:
            ym = (year, month)
            if latest_published is None or ym > latest_published:
                latest_published = ym
        if created:
            extra["date"] = created.split(".")[0]
        banner = find_image(year, month, "banner")
        if banner:
            extra["banner"] = banner
        cover = find_image(year, month, "cover")
        if cover:
            extra["cover"] = cover
        fm["extra"] = extra

        write_markdown(
            os.path.join(OUTPUT_DIR, year, month, "_index.md"),
            fm,
            "",
        )

    # Root — include latest published issue path
    root_extra = {}
    if latest_published:
        y, m = latest_published
        root_extra["latest_issue"] = f"{y}/{m}/_index.md"
    write_markdown(
        os.path.join(OUTPUT_DIR, "_index.md"),
        {"title": "కొత్తపల్లి", "extra": root_extra} if root_extra else {"title": "కొత్తపల్లి"},
        "",
    )

    # Year sections
    for year in sorted(years):
        write_markdown(
            os.path.join(OUTPUT_DIR, year, "_index.md"),
            {"title": year, "weight": int(year)},
            "",
        )

    print(f"Wrote section indexes for {len(years)} years, {len(issues)} issues")


def main():
    conn = psycopg2.connect(dbname=DB_NAME)
    cur = conn.cursor()

    try:
        # Build lookup maps
        issues = fetch_all(cur, "/type/issue")
        issue_names = {i["key"]: i.get("name", "") for i in issues}

        categories = fetch_all(cur, "/type/category")
        category_names = {c["key"]: c.get("name", "") for c in categories}

        article_counts = count_articles_per_issue(cur)

        print(f"Loaded {len(issue_names)} issues, {len(category_names)} categories")

        export_sections(cur, issue_names, article_counts)
        export_articles(cur, issue_names, category_names)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
