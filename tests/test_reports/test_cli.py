"""Tests for app/reports/cli.py."""

from __future__ import annotations

import argparse

from app.reports.cli import register_subparser, run_genre_report_command


class TestRegisterSubparser:
    def test_registers_genre_report_command(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_subparser(subparsers)
        args = parser.parse_args(["genre-report", "roguelite_strategy"])
        assert args.command == "genre-report"
        assert args.catalog_game == "roguelite_strategy"

    def test_registers_check_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_subparser(subparsers)
        args = parser.parse_args(["genre-report", "roguelite_strategy", "--check"])
        assert args.check is True

    def test_check_flag_defaults_false(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_subparser(subparsers)
        args = parser.parse_args(["genre-report", "roguelite_strategy"])
        assert args.check is False

    def test_output_arg_defaults_none(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_subparser(subparsers)
        args = parser.parse_args(["genre-report", "roguelite_strategy"])
        assert args.output is None

    def test_output_arg_accepts_path(self):
        from pathlib import Path

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_subparser(subparsers)
        args = parser.parse_args(["genre-report", "roguelite_strategy", "--output", "/tmp/out"])
        assert args.output == Path("/tmp/out")


class TestRunGenreReportCommand:
    def test_missing_catalog_game_returns_error_message(self):
        args = argparse.Namespace(
            catalog_game="nonexistent_game_xyz",
            check=False,
            output=None,
            db_path=":memory:",
        )
        result = run_genre_report_command(args)
        assert "nonexistent_game_xyz" in result.message
        assert "not found" in result.message

    def test_result_has_message_attribute(self):
        args = argparse.Namespace(
            catalog_game="nonexistent_game_xyz",
            check=False,
            output=None,
            db_path=":memory:",
        )
        result = run_genre_report_command(args)
        assert hasattr(result, "message")
        assert isinstance(result.message, str)
