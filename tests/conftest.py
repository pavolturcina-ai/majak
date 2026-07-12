"""Shared test fixtures.

DB-backed tests use a real Postgres (pgvector) via TEST_DATABASE_URL and are
skipped when it is not reachable, so the pure-logic suite always runs in CI.
"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db: test requires a live Postgres (pgvector)")


@pytest.fixture(scope="session")
def test_database_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL")
