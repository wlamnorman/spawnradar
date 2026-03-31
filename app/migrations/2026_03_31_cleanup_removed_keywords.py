"""Clean up removed and legacy keyword tags from the database.

Handles two things:

1. **Removed keywords** — deleted from keyword_groups.py on 2026-03-31.
   Deletes matching rows from igdb_game_tags and customer_game_tags.

2. **Legacy keyword→genre migration** — keywords that were mapped to IGDB
   genres at runtime via _LEGACY_KEYWORD_GENRE_MAP in repository.py
   (2d platformer→Platform, 3d platformer→Platform, logic puzzle→Puzzle,
   narrative adventure→Adventure). Persists the genre mapping into the DB
   so the runtime shim can be removed.

Usage:
    python -m app.migrations.2026_03_31_cleanup_removed_keywords [--db-path DB]

Safe to run multiple times (idempotent).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

# --- Removed keywords (delete from both igdb_game_tags and customer_game_tags) ---

REMOVED_KEYWORDS = (
    "2d platformer",
    "3d platformer",
    "action roguelike",
    "action rpg",
    "arena shooter",
    "auto battler",
    "boomer shooter",
    "brawler",
    "bullet heaven",
    "business simulation",
    "collectathon",
    "collectible card game",
    "colony simulator",
    "couch co-op",
    "creature collector",
    "crpg",
    "dating sim",
    "escape room",
    "farm",
    "first person horror",
    "flight simulation",
    "god game",
    "gothic horror",
    "grand strategy",
    "immersive sim",
    "life simulation",
    "logic puzzle",
    "mascot horror",
    "narrative adventure",
    "open world survival craft",
    "physics puzzle",
    "roguelike deckbuilder",
    "social deduction",
    "social simulation",
    "space strategy",
    "vehicle simulation",
)

# Keywords re-added after IGDB verification — protect from deletion.
READDED_KEYWORDS = {"automation", "micromanagement", "world building"}

# --- Legacy keyword → IGDB genre migration ---
# These keywords were being converted at runtime in repository.py.
# This migration persists the conversion into the DB rows directly.

LEGACY_KEYWORD_TO_GENRE = {
    "2d platformer": (8, "Platform"),
    "3d platformer": (8, "Platform"),
    "logic puzzle": (9, "Puzzle"),
    "narrative adventure": (31, "Adventure"),
}


def _placeholders(n: int) -> str:
    return ",".join("?" for _ in range(n))


def run(db_path: str, *, dry_run: bool = False) -> None:
    to_delete = [kw for kw in REMOVED_KEYWORDS if kw not in READDED_KEYWORDS]
    conn = sqlite3.connect(db_path)

    # ---- Part 1: Migrate legacy keywords in customer_games JSON columns ----

    print("=== Legacy keyword → genre migration (customer_games) ===\n")

    rows = conn.execute(
        "SELECT customer_game_id, igdb_genre_ids, igdb_keyword_ids FROM customer_games"
    ).fetchall()

    games_updated = 0
    for cg_id, genre_json, keyword_json in rows:
        genres = json.loads(genre_json or "[]")
        keywords = json.loads(keyword_json or "[]")

        new_genres = list(genres)
        new_keywords = []
        changed = False

        for kw in keywords:
            mapping = LEGACY_KEYWORD_TO_GENRE.get(kw)
            if mapping is not None:
                genre_id, genre_name = mapping
                if genre_id not in new_genres:
                    new_genres.append(genre_id)
                changed = True
                print(f"  {cg_id}: '{kw}' → genre {genre_id} ({genre_name})")
            else:
                new_keywords.append(kw)

        if changed:
            games_updated += 1
            if not dry_run:
                conn.execute(
                    """UPDATE customer_games
                       SET igdb_genre_ids = ?, igdb_keyword_ids = ?,
                           updated_at = datetime('now')
                       WHERE customer_game_id = ?""",
                    (json.dumps(new_genres), json.dumps(new_keywords), cg_id),
                )

    if games_updated == 0:
        print("  No customer games have legacy keywords.")
    else:
        print(
            f"\n  {games_updated} game(s) {'would be' if dry_run else ''} updated."
        )

    # Also update customer_game_tags for legacy keywords
    print("\n=== Legacy keyword → genre migration (customer_game_tags) ===\n")

    tags_migrated = 0
    for legacy_kw, (genre_id, _) in LEGACY_KEYWORD_TO_GENRE.items():
        legacy_rows = conn.execute(
            "SELECT customer_game_id FROM customer_game_tags WHERE tag_id = ?",
            (legacy_kw,),
        ).fetchall()
        for (cg_id,) in legacy_rows:
            tags_migrated += 1
            print(f"  {cg_id}: tag '{legacy_kw}' → genre tag {genre_id}")
            if not dry_run:
                # Add genre tag if not present
                conn.execute(
                    """INSERT OR IGNORE INTO customer_game_tags
                       (customer_game_id, tag_type, tag_id) VALUES (?, 'genre', ?)""",
                    (cg_id, genre_id),
                )
                # Remove legacy keyword tag
                conn.execute(
                    "DELETE FROM customer_game_tags WHERE customer_game_id = ? AND tag_id = ?",
                    (cg_id, legacy_kw),
                )

    if tags_migrated == 0:
        print("  No legacy keyword tags found in customer_game_tags.")

    # ---- Part 2: Delete removed keywords from igdb_game_tags ----

    print("\n=== Removed keywords cleanup (igdb_game_tags) ===\n")

    ph = _placeholders(len(to_delete))
    counts = conn.execute(
        f"SELECT tag_id, count(*) FROM igdb_game_tags WHERE tag_id IN ({ph}) GROUP BY tag_id",
        to_delete,
    ).fetchall()

    igdb_total = sum(c for _, c in counts)
    if igdb_total == 0:
        print("  No stale keywords in igdb_game_tags.")
    else:
        print(f"  Will delete {igdb_total} rows:")
        for tag_id, cnt in sorted(counts):
            print(f"    {tag_id}: {cnt} rows")
        if not dry_run:
            conn.execute(
                f"DELETE FROM igdb_game_tags WHERE tag_id IN ({ph})", to_delete
            )

    # ---- Part 3: Delete removed keywords from customer_game_tags ----

    print("\n=== Removed keywords cleanup (customer_game_tags) ===\n")

    cust_counts = conn.execute(
        f"SELECT tag_id, count(*) FROM customer_game_tags WHERE tag_id IN ({ph}) GROUP BY tag_id",
        to_delete,
    ).fetchall()

    cust_total = sum(c for _, c in cust_counts)
    if cust_total == 0:
        print("  No stale keywords in customer_game_tags.")
    else:
        print(f"  Will delete {cust_total} rows:")
        for tag_id, cnt in sorted(cust_counts):
            print(f"    {tag_id}: {cnt} rows")
        if not dry_run:
            conn.execute(
                f"DELETE FROM customer_game_tags WHERE tag_id IN ({ph})",
                to_delete,
            )

    if dry_run:
        print("\nDry run — no changes made.")
    else:
        conn.commit()
        print("\nDone. All changes committed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up removed and legacy keyword tags."
    )
    parser.add_argument(
        "--db-path",
        default="data/spawnradar.sqlite3",
        help="Path to SQLite database (default: data/spawnradar.sqlite3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making changes.",
    )
    args = parser.parse_args()
    run(args.db_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
