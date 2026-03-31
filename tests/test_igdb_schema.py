import os
import sqlite3
import tempfile

from app.database import initialize_database


def test_igdb_tables_and_identity_links_exist():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    try:
        initialize_database(db_path)
        con = sqlite3.connect(db_path)
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "igdb_games" in tables
            assert "igdb_game_tags" in tables
            assert "creator_account_game_tags" in tables
            assert "identity_links" in tables
        finally:
            con.close()
    finally:
        os.unlink(db_path)
