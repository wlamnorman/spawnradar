"""Match ranking service: score and rank creators for a CustomerGame."""

from __future__ import annotations

import inspect
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from threading import Lock

from app.creator_index.matching import (
    customer_game_tag_counts,
    customer_game_tag_keys,
    tag_weight,
)
from app.games.models import CustomerGame
from app.matches.models import (
    MATCH_WORKFLOW_STATUS_ORDER,
    MatchWorkflowState,
    MatchWorkflowStatus,
    ObservedTag,
    RankedMatch,
)
from app.matches.repository import MatchRepository, RankedSnapshotRow

log = logging.getLogger(__name__)

_SNAPSHOT_TTL_SECONDS = 180.0
_SNAPSHOT_MAX_ENTRIES = 10


@dataclass(frozen=True)
class _MatchRankSnapshot:
    built_at: float
    game_tags: tuple[tuple[str, int | str], ...]
    similar_game_ids: tuple[int, ...]
    reach_filter_max: int
    rows: tuple[RankedSnapshotRow, ...]


_snapshot_cache_lock = Lock()
_snapshot_cache: OrderedDict[tuple[object, ...], _MatchRankSnapshot] = (
    OrderedDict()
)


def _status_counts_for_rows(
    rows: tuple[RankedSnapshotRow, ...],
) -> dict[MatchWorkflowStatus, int]:
    counts: dict[MatchWorkflowStatus, int] = dict.fromkeys(
        MATCH_WORKFLOW_STATUS_ORDER, 0
    )
    for row in rows:
        counts[row.workflow_status] += 1
    return counts


def _status_filtered_rows(
    rows: tuple[RankedSnapshotRow, ...],
    status_filter: str,
) -> list[RankedSnapshotRow]:
    if status_filter == "all":
        return [row for row in rows if row.workflow_status != "not_pursuing"]
    if status_filter in MATCH_WORKFLOW_STATUS_ORDER:
        return [row for row in rows if row.workflow_status == status_filter]
    return list(rows)


def _apply_games_filters(
    rows: list[RankedSnapshotRow],
    *,
    min_relevant_games: int,
    max_relevant_games: int | None,
) -> list[RankedSnapshotRow]:
    return [
        row
        for row in rows
        if row.relevant_game_count >= min_relevant_games
        and (
            max_relevant_games is None
            or row.relevant_game_count <= max_relevant_games
        )
    ]


class MatchRankingService:
    """Rank content creators by coverage evidence for a customer game."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._repo = MatchRepository(db_path)

    def _repo_call(
        self,
        method_name: str,
        /,
        *args,
        conn,
        **kwargs,
    ):
        """Call a repository method, passing ``conn`` only when supported."""
        method = getattr(self._repo, method_name)
        if "conn" in inspect.signature(method).parameters:
            return method(*args, conn=conn, **kwargs)
        return method(*args, **kwargs)

    def _snapshot_key(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int,
        max_reach: int | None,
        contact_methods: tuple[str, ...],
    ) -> tuple[object, ...]:
        return (
            self._db_path,
            customer_game.customer_game_id,
            customer_game.updated_at,
            min_reach,
            max_reach,
            contact_methods,
        )

    def _get_cached_snapshot(
        self, key: tuple[object, ...]
    ) -> _MatchRankSnapshot | None:
        now = time.monotonic()
        with _snapshot_cache_lock:
            expired_keys = [
                cache_key
                for cache_key, snapshot in _snapshot_cache.items()
                if now - snapshot.built_at > _SNAPSHOT_TTL_SECONDS
            ]
            for expired_key in expired_keys:
                _snapshot_cache.pop(expired_key, None)
            snapshot = _snapshot_cache.get(key)
            if snapshot is None:
                return None
            touched_snapshot = replace(snapshot, built_at=now)
            _snapshot_cache[key] = touched_snapshot
            _snapshot_cache.move_to_end(key)
            return touched_snapshot

    def _store_snapshot(
        self,
        key: tuple[object, ...],
        snapshot: _MatchRankSnapshot,
    ) -> None:
        with _snapshot_cache_lock:
            _snapshot_cache[key] = snapshot
            _snapshot_cache.move_to_end(key)
            while len(_snapshot_cache) > _SNAPSHOT_MAX_ENTRIES:
                _snapshot_cache.popitem(last=False)

    def _get_or_build_snapshot(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int,
        max_reach: int | None,
        contact_methods: tuple[str, ...],
    ) -> _MatchRankSnapshot | None:
        game_tags = customer_game_tag_keys(customer_game)
        if not game_tags:
            return None

        key = self._snapshot_key(
            customer_game,
            min_reach=min_reach,
            max_reach=max_reach,
            contact_methods=contact_methods,
        )
        cached = self._get_cached_snapshot(key)
        if cached is not None:
            return cached

        cg_tags = customer_game_tag_counts(customer_game)
        total_weight = sum(tag_weight(k) for k in cg_tags)
        with self._repo.connection() as conn:
            similar_game_ids = self._repo_call(
                "resolve_similar_game_ids",
                customer_game.similar_game_names,
                conn=conn,
            )
            rows, reach_filter_max = self._repo_call(
                "rank_scored_snapshot",
                game_tags=game_tags,
                similar_game_ids=similar_game_ids,
                total_weight=total_weight,
                customer_game_id=customer_game.customer_game_id,
                min_reach=min_reach,
                max_reach=max_reach,
                contact_methods=contact_methods,
                conn=conn,
            )

        snapshot = _MatchRankSnapshot(
            built_at=time.monotonic(),
            game_tags=tuple(game_tags),
            similar_game_ids=tuple(similar_game_ids),
            reach_filter_max=reach_filter_max,
            rows=tuple(rows),
        )
        self._store_snapshot(key, snapshot)
        return snapshot

    def _update_cached_workflow_status(
        self,
        *,
        customer_game_id: str,
        account_id: str,
        status: MatchWorkflowStatus,
    ) -> None:
        now = time.monotonic()
        with _snapshot_cache_lock:
            for key, snapshot in list(_snapshot_cache.items()):
                if key[1] != customer_game_id:
                    continue
                updated = False
                next_rows: list[RankedSnapshotRow] = []
                for row in snapshot.rows:
                    if row.account_id == account_id:
                        next_rows.append(
                            RankedSnapshotRow(
                                account_id=row.account_id,
                                coverage_score=row.coverage_score,
                                reach=row.reach,
                                relevant_game_count=row.relevant_game_count,
                                workflow_status=status,
                            )
                        )
                        updated = True
                    else:
                        next_rows.append(row)
                if not updated:
                    continue
                _snapshot_cache[key] = _MatchRankSnapshot(
                    built_at=now,
                    game_tags=snapshot.game_tags,
                    similar_game_ids=snapshot.similar_game_ids,
                    reach_filter_max=snapshot.reach_filter_max,
                    rows=tuple(next_rows),
                )
                _snapshot_cache.move_to_end(key)

    def rank_matches(
        self,
        customer_game: CustomerGame,
        *,
        limit: int = 50,
        offset: int = 0,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
    ) -> tuple[
        list[RankedMatch],
        int,
        dict[MatchWorkflowStatus, int],
        int,  # reach_filter_max
        int,  # games_filter_max
    ]:
        """Return ranked creator matches for one customer game.

        Build or reuse a ranked snapshot for the current non-status
        filters, then slice and hydrate only the visible page rows.
        """
        started_at = time.perf_counter()
        snapshot = self._get_or_build_snapshot(
            customer_game,
            min_reach=min_reach,
            max_reach=max_reach,
            contact_methods=contact_methods,
        )
        if snapshot is None:
            return (
                [],
                0,
                dict.fromkeys(MATCH_WORKFLOW_STATUS_ORDER, 0),
                0,
                0,
            )

        cg_tags = customer_game_tag_counts(customer_game)
        status_counts = _status_counts_for_rows(snapshot.rows)
        status_rows = _status_filtered_rows(snapshot.rows, status_filter)
        games_filter_max = max(
            (row.relevant_game_count for row in status_rows),
            default=0,
        )
        filtered_rows = _apply_games_filters(
            status_rows,
            min_relevant_games=min_relevant_games,
            max_relevant_games=max_relevant_games,
        )
        total_count = len(filtered_rows)
        page_rows = filtered_rows[offset : offset + limit]
        elapsed_ms = (time.perf_counter() - started_at) * 1000

        if not page_rows:
            log.info(
                "[matches] rank empty game_id=%s elapsed_ms=%.1f",
                customer_game.customer_game_id,
                elapsed_ms,
            )
            return (
                [],
                total_count,
                status_counts,
                snapshot.reach_filter_max,
                games_filter_max,
            )

        page_ids = [row.account_id for row in page_rows]

        # --- Hydrate page rows -----------------------------------------
        hydrate_started_at = time.perf_counter()
        with self._repo.connection() as conn:
            profiles = self._repo_call(
                "get_creator_profiles",
                page_ids,
                conn=conn,
            )
            relevant_games = self._repo_call(
                "get_relevant_games",
                page_ids,
                snapshot.game_tags,
                snapshot.similar_game_ids,
                per_account_limit=10,
                conn=conn,
            )

            # Per-creator tag counts for the overlap-tag display
            page_tag_counts = self._repo_call(
                "query_creator_tag_counts",
                game_tags=snapshot.game_tags,
                account_ids=page_ids,
                conn=conn,
            )
            # Compute overlap tags per page creator
            overlap_tags_by_id: dict[
                str, tuple[tuple[str, int | str], ...]
            ] = {}
            for account_id in page_ids:
                tc = page_tag_counts.get(account_id, {})
                overlap_tags_by_id[account_id] = tuple(
                    sorted(
                        (k for k in cg_tags if k in tc),
                        key=lambda k: (k[0], str(k[1])),
                    )
                )

            workflow_states = self._repo_call(
                "get_match_workflow_states",
                customer_game_id=customer_game.customer_game_id,
                account_ids=page_ids,
                conn=conn,
            )
        hydrate_elapsed_ms = (time.perf_counter() - hydrate_started_at) * 1000

        results: list[RankedMatch] = []
        for row in page_rows:
            account_id = row.account_id
            profile = profiles.get(account_id)
            if profile is None:
                continue
            tc = page_tag_counts.get(account_id, {})
            overlap = overlap_tags_by_id.get(account_id, ())
            results.append(
                RankedMatch(
                    profile=profile,
                    coverage_score=row.coverage_score,
                    overlap_tags=overlap,
                    observed_tags=tuple(
                        ObservedTag(
                            tag_type=tag_type,
                            tag_id=tag_id,
                            observed_game_count=tc.get((tag_type, tag_id), 0),
                        )
                        for tag_type, tag_id in overlap
                    ),
                    relevant_game_count=row.relevant_game_count,
                    workflow=workflow_states.get(
                        account_id, MatchWorkflowState()
                    ),
                    relevant_games=tuple(relevant_games.get(account_id, [])),
                )
            )

        log.info(
            "[matches] rank complete game_id=%s total=%s page_size=%s sql_ms=%.1f hydrate_ms=%.1f total_ms=%.1f",
            customer_game.customer_game_id,
            total_count,
            len(results),
            elapsed_ms,
            hydrate_elapsed_ms,
            (time.perf_counter() - started_at) * 1000,
        )
        return (
            results,
            total_count,
            status_counts,
            snapshot.reach_filter_max,
            games_filter_max,
        )

    def count_ranked_matches(
        self,
        customer_game: CustomerGame,
        *,
        min_reach: int = 0,
        max_reach: int | None = None,
        min_relevant_games: int = 0,
        max_relevant_games: int | None = None,
        contact_methods: tuple[str, ...] = (),
        status_filter: str = "all",
    ) -> tuple[int, dict[MatchWorkflowStatus, int]]:
        """Return filtered match counts without rebuilding ranked SQL."""
        snapshot = self._get_or_build_snapshot(
            customer_game,
            min_reach=min_reach,
            max_reach=max_reach,
            contact_methods=contact_methods,
        )
        if snapshot is None:
            return 0, dict.fromkeys(MATCH_WORKFLOW_STATUS_ORDER, 0)

        status_counts = _status_counts_for_rows(snapshot.rows)
        status_rows = _status_filtered_rows(snapshot.rows, status_filter)
        filtered_rows = _apply_games_filters(
            status_rows,
            min_relevant_games=min_relevant_games,
            max_relevant_games=max_relevant_games,
        )
        return len(filtered_rows), status_counts

    def update_match_workflow(
        self,
        customer_game: CustomerGame,
        *,
        account_id: str,
        status: MatchWorkflowStatus,
        notes: str,
    ) -> MatchWorkflowState:
        """Persist workflow state for one match on one customer game."""
        state = self._repo.upsert_match_workflow_state(
            customer_game_id=customer_game.customer_game_id,
            account_id=account_id,
            status=status,
            notes=notes,
        )
        self._update_cached_workflow_status(
            customer_game_id=customer_game.customer_game_id,
            account_id=account_id,
            status=status,
        )
        return state
