"""Shared pytest fixtures for Wayfinder server and integration tests."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from core.db.database import DEFAULT_DB_PATH
from core.server import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Module-level test client ensuring lifespan hooks execute with isolated test config and seeded test DB."""
    test_sandbox = tmp_path_factory.mktemp("wayfinder_test_sandbox")
    test_config_file = test_sandbox / "config.json"
    test_db_file = test_sandbox / "test_wayfinder.db"

    # Seed the isolated test database so server tests have combat chunks
    from core.db.seeds.sekiro_seed import seed_sekiro
    seed_sekiro(test_db_file)

    old_cfg_env = os.environ.get("WAYFINDER_CONFIG_PATH")
    old_db_env = os.environ.get("WAYFINDER_DB_PATH")
    os.environ["WAYFINDER_CONFIG_PATH"] = str(test_config_file)
    os.environ["WAYFINDER_DB_PATH"] = str(test_db_file)

    app = create_app(db_path=test_db_file)
    with TestClient(app) as test_client:
        yield test_client

    if old_cfg_env is not None:
        os.environ["WAYFINDER_CONFIG_PATH"] = old_cfg_env
    else:
        os.environ.pop("WAYFINDER_CONFIG_PATH", None)

    if old_db_env is not None:
        os.environ["WAYFINDER_DB_PATH"] = old_db_env
    else:
        os.environ.pop("WAYFINDER_DB_PATH", None)
