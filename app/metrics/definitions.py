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
TRIALS_STARTED = CounterMetricDefinition(
    key="trials_started",
    prometheus_name="spawnradar_trials_started_total",
    help_text="Total number of product trials started.",
    definition="Count once when a user enters the product trial for the first time.",
)
TRIALS_EXPIRED_WITHOUT_CONVERSION = CounterMetricDefinition(
    key="trials_expired_without_conversion",
    prometheus_name="spawnradar_trials_expired_without_conversion_total",
    help_text="Total number of trials that expired without converting.",
    definition=(
        "Count once when a trial ends and the user never entered paid access "
        "before expiry."
    ),
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
MESSAGE_TEMPLATES_CREATED = CounterMetricDefinition(
    key="message_templates_created",
    prometheus_name="spawnradar_message_templates_created_total",
    help_text="Total number of message templates created.",
    definition="Count once when a new message template row is inserted.",
)

COUNTER_METRICS: tuple[CounterMetricDefinition, ...] = (
    ACCOUNTS_CREATED,
    SESSIONS_STARTED,
    TRIALS_STARTED,
    TRIALS_EXPIRED_WITHOUT_CONVERSION,
    PAID_SUBSCRIPTIONS_STARTED,
    PAID_ACCESS_ENDED,
    GAMES_CREATED,
    GAMES_DELETED,
    GAMES_DUPLICATED,
    MESSAGE_TEMPLATES_CREATED,
)

DISCOVERY_RUNS_STARTED = CounterMetricDefinition(
    key="discovery_runs_started",
    prometheus_name="spawnradar_discovery_runs_started_total",
    help_text="Total number of discovery runs started.",
    definition="Count once when a discovery run is accepted and queued.",
)
DISCOVERY_RUNS_COMPLETED = CounterMetricDefinition(
    key="discovery_runs_completed",
    prometheus_name="spawnradar_discovery_runs_completed_total",
    help_text="Total number of discovery runs completed successfully.",
    definition=(
        "Count once when a discovery run finishes successfully, even if it "
        "finds zero prospects."
    ),
)
DISCOVERY_RUNS_FAILED = CounterMetricDefinition(
    key="discovery_runs_failed",
    prometheus_name="spawnradar_discovery_runs_failed_total",
    help_text="Total number of discovery runs that failed.",
    definition="Count once when a started discovery run does not finish successfully.",
)
DISCOVERY_RUNS_NO_PROSPECTS = CounterMetricDefinition(
    key="discovery_runs_no_prospects",
    prometheus_name="spawnradar_discovery_runs_no_prospects_total",
    help_text="Total number of completed discovery runs that found zero prospects.",
    definition=(
        "Count once when a completed discovery run finishes with "
        "prospects_discovered equal to zero."
    ),
)
PROSPECTS_DISCOVERED = CounterMetricDefinition(
    key="prospects_discovered",
    prometheus_name="spawnradar_prospects_discovered_total",
    help_text="Total number of raw prospects discovered.",
    definition="Total raw candidates returned by sources across completed runs.",
)
PROSPECTS_SCORED = CounterMetricDefinition(
    key="prospects_scored",
    prometheus_name="spawnradar_prospects_scored_total",
    help_text="Total number of prospects that reached scoring.",
    definition="Total candidates that reached scoring across completed runs.",
)
PROSPECTS_QUEUED = CounterMetricDefinition(
    key="prospects_queued",
    prometheus_name="spawnradar_prospects_queued_total",
    help_text="Total number of new prospects queued for review.",
    definition="Total new queue items created across completed runs.",
)

DISCOVERY_COUNTER_METRICS: tuple[CounterMetricDefinition, ...] = (
    DISCOVERY_RUNS_STARTED,
    DISCOVERY_RUNS_COMPLETED,
    DISCOVERY_RUNS_FAILED,
    DISCOVERY_RUNS_NO_PROSPECTS,
    PROSPECTS_DISCOVERED,
    PROSPECTS_SCORED,
    PROSPECTS_QUEUED,
)

DISCOVERY_RUN_PROSPECTS_DISCOVERED = HistogramMetricDefinition(
    prometheus_name="spawnradar_discovery_run_prospects_discovered",
    help_text="Distribution of raw prospects discovered per completed run.",
    definition="Observe the number of raw prospects returned in each completed discovery run.",
    buckets=(0, 1, 3, 5, 10, 20, 30, 50, 75, 100),
)
DISCOVERY_RUN_PROSPECTS_SCORED = HistogramMetricDefinition(
    prometheus_name="spawnradar_discovery_run_prospects_scored",
    help_text="Distribution of prospects scored per completed run.",
    definition="Observe the number of candidates that reached scoring in each completed discovery run.",
    buckets=(0, 1, 3, 5, 10, 20, 30, 50, 75, 100),
)
DISCOVERY_RUN_PROSPECTS_QUEUED = HistogramMetricDefinition(
    prometheus_name="spawnradar_discovery_run_prospects_queued",
    help_text="Distribution of new queued prospects per completed run.",
    definition="Observe the number of new queue items created in each completed discovery run.",
    buckets=(0, 1, 3, 5, 10, 20, 30, 50, 75, 100),
)
PROSPECT_SCORE_SCORED = HistogramMetricDefinition(
    prometheus_name="spawnradar_prospect_score_scored",
    help_text="Distribution of all scored prospect final scores.",
    definition="Observe final scores for every prospect that reaches scoring.",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
PROSPECT_SCORE_QUEUED = HistogramMetricDefinition(
    prometheus_name="spawnradar_prospect_score_queued",
    help_text="Distribution of queued prospect final scores.",
    definition="Observe final scores for prospects that create new queue items.",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
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
TIME_TO_FIRST_DISCOVERY_RUN = TimingMetricDefinition(
    key="time_to_first_discovery_run",
    avg_name="spawnradar_time_to_first_discovery_run_hours_avg",
    p50_name="spawnradar_time_to_first_discovery_run_hours_p50",
    p90_name="spawnradar_time_to_first_discovery_run_hours_p90",
    help_text="Time from account creation to first discovery run in hours.",
    definition=(
        "Derived from account creation time to the user's first discovery_runs_started event."
    ),
)

TIMING_METRICS: tuple[TimingMetricDefinition, ...] = (
    TIME_TO_FIRST_GAME_CREATED,
    TIME_TO_FIRST_DISCOVERY_RUN,
)
