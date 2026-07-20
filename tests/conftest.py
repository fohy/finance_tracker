from __future__ import annotations

from pathlib import Path

import pytest

from finance import create_app


@pytest.fixture
def app(tmp_path: Path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test-finflow.db"),
        "SEED_DEMO": False,
    })


@pytest.fixture
def client(app):
    return app.test_client()
