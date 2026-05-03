"""Benchmark: measure resolve_similar_game_ids with parent_game LEFT JOIN.

Run:
    python -m tests.bench_canonical_resolution [--db-path PATH] [--iterations N]

Uses the real local database to measure actual query performance.
"""

from __future__ import annotations

import argparse
import statistics
import time

from app.config import Settings
from app.database import get_connection
from app.matches.repository import MatchRepository


def _sample_game_names(db_path: str, n: int = 10) -> list[str]:
    """Pick N random game names from the local DB."""
    with get_connection(db_path) as con:
        rows = con.execute(
            "SELECT name FROM igdb_games ORDER BY RANDOM() LIMIT ?", (n,)
        ).fetchall()
    return [r["name"] for r in rows]


def bench_resolve(
    db_path: str, names: list[str], iterations: int
) -> list[float]:
    repo = MatchRepository(db_path)
    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        repo.resolve_similar_game_ids(names)
        elapsed_ms = (time.perf_counter() - start) * 1000
        times.append(elapsed_ms)
    return times


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark canonical resolution"
    )
    parser.add_argument("--db-path", default="", help="SQLite path")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--names", type=int, default=15, help="Number of game names to resolve"
    )
    args = parser.parse_args()

    db_path = args.db_path or Settings.from_env().db_path

    with get_connection(db_path) as con:
        total_games = con.execute(
            "SELECT COUNT(*) FROM igdb_games"
        ).fetchone()[0]
        games_with_parent = con.execute(
            "SELECT COUNT(*) FROM igdb_games WHERE parent_game_id IS NOT NULL"
        ).fetchone()[0]
    print(f"DB: {total_games} games, {games_with_parent} with parent_game_id")

    names = _sample_game_names(db_path, args.names)
    print(f"Resolving {len(names)} names x {args.iterations} iterations\n")

    times = bench_resolve(db_path, names, args.iterations)

    print(f"  min:    {min(times):.3f} ms")
    print(f"  median: {statistics.median(times):.3f} ms")
    print(f"  mean:   {statistics.mean(times):.3f} ms")
    print(f"  p95:    {sorted(times)[int(len(times) * 0.95)]:.3f} ms")
    print(f"  max:    {max(times):.3f} ms")


if __name__ == "__main__":
    main()
