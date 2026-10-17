"""Tests for Wayfinder Phase 4 micro-daemon server (core/server.py).

Validates:
- Health check probe (/health)
- Game & encounter catalog (/games)
- Tactical query distillation & response envelope (/query)
- Deterministic fallback under missing LLM
- Input validation and error cases
"""

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


def test_root_endpoint(client: TestClient):
    """Verifies the root status route."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Wayfinder Daemon"
    assert data["status"] == "online"
    assert "/query" in data["endpoints"]


def test_health_endpoint(client: TestClient):
    """Verifies database connectivity and diagnostics."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["db_ok"] is True
    assert data["indexed_chunks"] > 0
    assert data["status"] in ("healthy", "degraded")
    assert "llama" in data["model"].lower() or len(data["model"]) > 0


def test_games_endpoint(client: TestClient):
    """Verifies indexed games and encounters catalog."""
    response = client.get("/games")
    assert response.status_code == 200
    data = response.json()
    assert "games" in data
    assert len(data["games"]) >= 1

    sekiro = next((g for g in data["games"] if g["game_id"] == "sekiro"), None)
    assert sekiro is not None
    assert sekiro["chunk_count"] > 0
    assert len(sekiro["encounters"]) > 0


def test_query_endpoint_success(client: TestClient):
    """Verifies tactical search and distillation for a known combat term."""
    payload = {
        "game_id": "sekiro",
        "query": "lightning reversal",
    }
    response = client.post("/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["found"] is True
    assert data["card"] is not None

    card = data["card"]
    assert card["game"] == "sekiro"
    assert len(card["summary"]) > 0
    assert len(card["tactical_cues"]) >= 1

    cue = card["tactical_cues"][0]
    assert "tell" in cue
    assert "action" in cue
    assert "outcome" in cue

    telemetry = data["telemetry"]
    assert telemetry["retrieval_ms"] >= 0.0
    assert telemetry["total_ms"] > 0.0


def test_query_endpoint_not_found(client: TestClient):
    """Verifies proper envelope response when no chunks match."""
    payload = {
        "game_id": "sekiro",
        "query": "supercalifragilisticexpialidocious_nonsense_term",
    }
    response = client.post("/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["found"] is False
    assert data["card"] is None
    assert "No combat guides found" in data["message"]
    assert data["telemetry"]["total_ms"] >= 0.0


def test_query_validation_error(client: TestClient):
    """Verifies 422 error for empty or invalid query strings."""
    response = client.post("/query", json={"game_id": "sekiro", "query": ""})
    assert response.status_code == 422


def test_ingest_markdown_and_query(client: TestClient):
    """Verifies markdown guide ingestion, slugification, and immediate queryability."""
    markdown_content = """# Phase 1: Roaring Leap
When the beast crouches low and lets out a high pitched shriek, it is preparing a leaping slam.
Jump backwards or sprint diagonally to clear the blast radius.

# Phase 2: Terror Screech
The headless terror scream builds fear rapidly.
Equip the Phoenix Lilac Umbrella or sprint far away to avoid sudden death.
"""
    payload = {
        "game_id": "sekiro",
        "encounter_id": "Great Guardian Ape",  # Tests slugification -> great_guardian_ape
        "source_type": "markdown",
        "content": markdown_content,
        "filename": "ape_guide.md",
    }

    # 1. Ingest
    res = client.post("/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["encounter_id"] == "great_guardian_ape"
    assert data["chunks_indexed"] >= 2
    assert data["latency_ms"] > 0.0

    # 2. Immediately query the newly indexed chunks
    query_payload = {
        "game_id": "sekiro",
        "query": "terror screech phoenix lilac umbrella",
        "encounter_id": "great_guardian_ape",
    }
    q_res = client.post("/query", json=query_payload)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["found"] is True
    assert q_data["card"] is not None
    assert "great guardian ape" in q_data["card"]["encounter"].lower()


def test_ingest_missing_content_and_url(client: TestClient):
    """Verifies 400 when neither URL nor content is provided."""
    payload = {
        "game_id": "sekiro",
        "encounter_id": "genichiro",
    }
    res = client.post("/ingest", json=payload)
    assert res.status_code == 400


def test_ingest_unsupported_url(client: TestClient):
    """Verifies 400 when unsupported domain URL is provided."""
    payload = {
        "game_id": "sekiro",
        "encounter_id": "genichiro",
        "url": "https://example.com/some_random_page",
    }
    res = client.post("/ingest", json=payload)
    assert res.status_code == 400


def test_models_endpoint(client: TestClient):
    """Verifies discovery of installed local models."""
    res = client.get("/models")
    assert res.status_code == 200
    data = res.json()
    assert "active_model" in data
    assert "available_models" in data
    assert isinstance(data["available_models"], list)
    assert len(data["available_models"]) >= 1
    assert data["active_model"] in data["available_models"]


def test_set_model_endpoint(client: TestClient):
    """Verifies hot-swapping the active model and checking reflection in health probe."""
    test_model = "qwen2.5:1.5b"
    res = client.post("/settings/model", json={"model": test_model})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["active_model"] == test_model

    # Check health probe reflects the updated model
    h_res = client.get("/health")
    assert h_res.status_code == 200
    assert h_res.json()["model"] == test_model

    # Check /models reflects the updated model
    m_res = client.get("/models")
    assert m_res.status_code == 200
    assert m_res.json()["active_model"] == test_model


def test_set_model_empty_rejected(client: TestClient):
    """Verifies 422 validation failure when empty model string is provided."""
    res = client.post("/settings/model", json={"model": ""})
    assert res.status_code == 422


def test_default_db_path_resolution(monkeypatch):
    """Verifies WAYFINDER_DB_PATH environment override."""
    from core.db.database import get_default_db_path

    custom_path = "/tmp/custom_test_wayfinder.db"
    monkeypatch.setenv("WAYFINDER_DB_PATH", custom_path)
    resolved = get_default_db_path()
    assert str(resolved) == custom_path


def test_clean_schema_init_in_frozen_mode(tmp_path, monkeypatch):
    """Verifies that in a frozen binary, a clean unseeded schema is initialized in user app data dir."""
    import sys
    from core.db import database

    fake_app_data = tmp_path / "user_data"
    monkeypatch.setattr(database, "APP_DATA_DIR", fake_app_data)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("WAYFINDER_DB_PATH", raising=False)

    # First call should create user dir and initialize clean database schema
    target_db = database.get_default_db_path()
    assert target_db == fake_app_data / "wayfinder.db"
    assert target_db.exists()

    # Verify clean database connection and schema work with 0 seeded chunks
    with database.get_connection(target_db) as conn:
        cursor = conn.execute("SELECT count(*) as total FROM guide_chunks")
        assert cursor.fetchone()["total"] == 0


def test_wayfinder_config_path_override(tmp_path, monkeypatch):
    """Verifies WAYFINDER_CONFIG_PATH isolates settings persistence."""
    from core.config import get_config_path, load_config, save_config

    custom_cfg = tmp_path / "custom_config.json"
    monkeypatch.setenv("WAYFINDER_CONFIG_PATH", str(custom_cfg))

    assert get_config_path() == custom_cfg
    save_config({"model": "test-model:latest"})

    assert custom_cfg.exists()
    loaded = load_config()
    assert loaded["model"] == "test-model:latest"


def test_llm_model_tag_matching():
    """Verifies that closest model tag is matched when tag suffix is missing."""
    from core.llm.client import LocalLLMClient

    installed = ["llama3.2:3b", "qwen2.5-coder:3b"]

    # Exact match
    assert LocalLLMClient.find_best_matching_model("llama3.2:3b", installed) == "llama3.2:3b"

    # Prefix match without tag
    assert LocalLLMClient.find_best_matching_model("llama3.2", installed) == "llama3.2:3b"

    # Tag mismatch (e.g. :latest -> :3b)
    assert LocalLLMClient.find_best_matching_model("llama3.2:latest", installed) == "llama3.2:3b"

    # Non-existent model returns None
    assert LocalLLMClient.find_best_matching_model("nonexistent:1b", installed) is None
