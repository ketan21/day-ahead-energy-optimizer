"""Shared fixtures for the DAEO engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from daeo.api.app import create_app
from daeo.api.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        api_token="test-token",
        demo=True,
        require_auth=True,
    )


@pytest.fixture
def client(settings: Settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}
