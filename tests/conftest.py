import pytest

from app.auth.repository import SessionRepository, UserRepository
from app.auth.service import AuthService
from app.billing.repository import SubscriptionRepository
from app.billing.service import BillingService
from app.database import initialize_database
from app.games.repository import CustomerGameRepository
from app.games.service import CustomerGameService
from app.metrics.repository import MetricsRepository
from app.metrics.service import MetricsService


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)
    return path


@pytest.fixture
def user_repo(db_path):
    return UserRepository(db_path)


@pytest.fixture
def session_repo(db_path):
    return SessionRepository(db_path)


@pytest.fixture
def auth_service(user_repo, session_repo, metrics_service):
    return AuthService(
        user_repo, session_repo, metrics_service=metrics_service
    )


@pytest.fixture
def metrics_repo(db_path):
    return MetricsRepository(db_path)


@pytest.fixture
def metrics_service(metrics_repo, sub_repo):
    return MetricsService(metrics_repo, sub_repo)


@pytest.fixture
def game_repo(db_path):
    return CustomerGameRepository(db_path)


@pytest.fixture
def game_service(game_repo, metrics_service):
    return CustomerGameService(game_repo, metrics_service)


@pytest.fixture
def sub_repo(db_path):
    return SubscriptionRepository(db_path)


@pytest.fixture
def billing_service(sub_repo, game_repo, metrics_service):
    return BillingService(
        sub_repo,
        game_repo,
        metrics_service=metrics_service,
        paddle_api_key="test_api_key",
        paddle_client_side_token="test_123456789012345678901234567",
        paddle_indie_price_id="pri_indie",
        paddle_environment="sandbox",
    )


@pytest.fixture
def registered_user(auth_service):
    return auth_service.register("test@example.com", "password123")


@pytest.fixture
def sample_game(game_service, registered_user):
    return game_service.create_game(
        user_id=registered_user.user_id,
        name="PuzzleQuest",
        summary="A daily browser word puzzle challenge for fast-thinking trivia fans.",
        description="A daily browser-based puzzle game for word puzzle fans",
        website_url=None,
        igdb_genre_ids=[9],  # Puzzle
    )
