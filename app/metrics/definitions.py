"""Canonical metric definitions used for durable tracking and export."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CounterMetricDefinition:
    """Definition for an append-only business counter."""

    key: str
    prometheus_name: str
    help_text: str
    definition: str
    label_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistogramMetricDefinition:
    """Definition for a histogram exported from durable observations."""

    prometheus_name: str
    help_text: str
    definition: str
    buckets: tuple[float, ...]


@dataclass(frozen=True)
class TimingMetricDefinition:
    """Definition for a derived time-to-first metric family."""

    key: str
    avg_name: str
    p50_name: str
    p90_name: str
    help_text: str
    definition: str


ACCOUNTS_CREATED = CounterMetricDefinition(
    key="accounts_created",
    prometheus_name="spawnradar_accounts_created_total",
    help_text="Total number of SpawnRadar accounts created.",
    definition="Count once when a brand-new user account is created.",
)
SESSIONS_STARTED = CounterMetricDefinition(
    key="sessions_started",
    prometheus_name="spawnradar_sessions_started_total",
    help_text="Total number of authenticated sessions started.",
    definition="Count once when an authenticated app session is created.",
)
PAID_SUBSCRIPTIONS_STARTED = CounterMetricDefinition(
    key="paid_subscriptions_started",
    prometheus_name="spawnradar_paid_subscriptions_started_total",
    help_text="Total number of paid subscriptions started.",
    definition="Count once when paid billing starts.",
)
PAID_ACCESS_ENDED = CounterMetricDefinition(
    key="paid_access_ended",
    prometheus_name="spawnradar_paid_access_ended_total",
    help_text="Total number of paid access periods that ended.",
    definition=(
        "Count once when paid access becomes unavailable for any reason. "
        "Uses a low-cardinality reason label."
    ),
    label_names=("reason",),
)
GAMES_CREATED = CounterMetricDefinition(
    key="games_created",
    prometheus_name="spawnradar_games_created_total",
    help_text="Total number of games created through the normal create flow.",
    definition=(
        "Count once when a game is created through the normal create flow, "
        "excluding explicit duplicates."
    ),
)
GAMES_DELETED = CounterMetricDefinition(
    key="games_deleted",
    prometheus_name="spawnradar_games_deleted_total",
    help_text="Total number of games deleted.",
    definition="Count once when a game is deleted.",
)
GAMES_DUPLICATED = CounterMetricDefinition(
    key="games_duplicated",
    prometheus_name="spawnradar_games_duplicated_total",
    help_text="Total number of game duplication actions.",
    definition="Count once when a game is created via explicit duplicate or copy.",
)
DISCOVERY_RUNS_COMPLETED = CounterMetricDefinition(
    key="discovery_runs_completed",
    prometheus_name="spawnradar_discovery_runs_completed_total",
    help_text="Total number of discovery pipeline runs completed.",
    definition=(
        "Count once per game per scheduled or on-demand discovery run. "
        "The value field stores the number of new creators found."
    ),
)
PROSPECT_PAGES_VIEWED = CounterMetricDefinition(
    key="prospect_pages_viewed",
    prometheus_name="spawnradar_prospect_pages_viewed_total",
    help_text="Total number of prospect page views.",
    definition="Count once when a user views the ranked prospects page for a game.",
)
COUNTER_METRICS: tuple[CounterMetricDefinition, ...] = (
    ACCOUNTS_CREATED,
    SESSIONS_STARTED,
    PAID_SUBSCRIPTIONS_STARTED,
    PAID_ACCESS_ENDED,
    GAMES_CREATED,
    GAMES_DELETED,
    GAMES_DUPLICATED,
    DISCOVERY_RUNS_COMPLETED,
    PROSPECT_PAGES_VIEWED,
)

TIME_TO_FIRST_GAME_CREATED = TimingMetricDefinition(
    key="time_to_first_game_created",
    avg_name="spawnradar_time_to_first_game_created_hours_avg",
    p50_name="spawnradar_time_to_first_game_created_hours_p50",
    p90_name="spawnradar_time_to_first_game_created_hours_p90",
    help_text="Time from account creation to first game creation in hours.",
    definition=(
        "Derived from account creation time to the user's first games_created event."
    ),
)

TIMING_METRICS: tuple[TimingMetricDefinition, ...] = (
    TIME_TO_FIRST_GAME_CREATED,
)
