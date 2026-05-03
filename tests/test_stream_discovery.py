import pytest

from app.creator_index.stream_discovery import (
    TwitchCategory,
    TwitchCategorySearchPage,
    TwitchGame,
    TwitchGamesPage,
    TwitchPagination,
    build_category_search_query_params,
    build_games_query_params,
    build_streams_query_params,
    parse_category_search_page,
    parse_games_page,
)


def test_build_streams_query_params_includes_repeated_filters():
    params = build_streams_query_params(
        game_ids=("1994", "33214"),
        languages=("en", "de"),
        user_logins=("tacticalrow",),
        stream_type="live",
        first=50,
        after="cursor-1",
    )

    assert params == (
        ("first", "50"),
        ("type", "live"),
        ("user_login", "tacticalrow"),
        ("game_id", "1994"),
        ("game_id", "33214"),
        ("language", "en"),
        ("language", "de"),
        ("after", "cursor-1"),
    )


def test_build_streams_query_params_rejects_before_and_after_together():
    with pytest.raises(ValueError, match="before and after"):
        build_streams_query_params(before="a", after="b")


def test_build_category_search_query_params():
    params = build_category_search_query_params(
        query=" Slay the Spire II ",
        first=10,
        after="cursor-1",
    )

    assert params == (
        ("query", "Slay the Spire II"),
        ("first", "10"),
        ("after", "cursor-1"),
    )


def test_build_games_query_params():
    params = build_games_query_params(
        igdb_game_ids=(296831,),
        names=("Slay the Spire II",),
    )

    assert params == (
        ("name", "Slay the Spire II"),
        ("igdb_id", "296831"),
    )


def test_parse_category_search_page():
    page = parse_category_search_page(
        {
            "data": [
                {
                    "id": "509658",
                    "name": "Slay the Spire",
                    "box_art_url": "https://example.test/box.jpg",
                }
            ],
            "pagination": {"cursor": "next"},
        }
    )

    assert page == TwitchCategorySearchPage(
        data=(
            TwitchCategory(
                category_id="509658",
                name="Slay the Spire",
                box_art_url="https://example.test/box.jpg",
            ),
        ),
        pagination=TwitchPagination(cursor="next"),
    )


def test_parse_games_page():
    page = parse_games_page(
        {
            "data": [
                {
                    "id": "1435206302",
                    "name": "Slay the Spire II",
                    "box_art_url": "https://example.test/box.jpg",
                    "igdb_id": "296831",
                }
            ]
        }
    )

    assert page == TwitchGamesPage(
        data=(
            TwitchGame(
                twitch_game_id="1435206302",
                name="Slay the Spire II",
                box_art_url="https://example.test/box.jpg",
                igdb_game_id="296831",
            ),
        )
    )
