import pytest

from app.auth.repository import SessionRepository, UserRepository
from app.auth.service import AuthService
from app.billing.repository import (
    DiscoveryRunRepository,
    SubscriptionRepository,
)
from app.billing.service import BillingService
from app.database import initialize_database
from app.games.repository import (
    AssetRepository,
    GameRepository,
    MessageTemplateRepository,
)
from app.games.service import GameService
from app.prospects.repository import (
    DraftItemRepository,
    OutcomeRepository,
    ProspectRepository,
)
from app.prospects.service import ProspectService


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
def auth_service(user_repo, session_repo):
    return AuthService(user_repo, session_repo)


@pytest.fixture
def game_repo(db_path):
    return GameRepository(db_path)


@pytest.fixture
def asset_repo(db_path):
    return AssetRepository(db_path)


@pytest.fixture
def template_repo(db_path):
    return MessageTemplateRepository(db_path)


@pytest.fixture
def game_service(game_repo, asset_repo, template_repo):
    return GameService(game_repo, asset_repo, template_repo)


@pytest.fixture
def prospect_repo(db_path):
    return ProspectRepository(db_path)


@pytest.fixture
def draft_repo(db_path):
    return DraftItemRepository(db_path)


@pytest.fixture
def outcome_repo(db_path):
    return OutcomeRepository(db_path)


@pytest.fixture
def prospect_service(draft_repo, outcome_repo):
    return ProspectService(draft_repo, outcome_repo)


@pytest.fixture
def sub_repo(db_path):
    return SubscriptionRepository(db_path)


@pytest.fixture
def run_repo(db_path):
    return DiscoveryRunRepository(db_path)


@pytest.fixture
def billing_service(sub_repo, game_repo, run_repo):
    return BillingService(
        sub_repo,
        game_repo,
        run_repo,
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
        description="A daily browser-based puzzle game for word puzzle fans",
        genre_tags_raw="puzzle, word game, daily",
        audience_tags_raw="wordle fans, puzzle lovers",
        platform_tags=["browser"],
        website_url=None,
    )
