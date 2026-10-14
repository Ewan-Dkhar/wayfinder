"""Tests for Wayfinder Phase 4 micro-daemon server (core/server.py).

Validates:
- Health check probe (/health)
- Game & encounter catalog (/games)
- Tactical query distillation & response envelope (/query)
- Deterministic fallback under missing LLM
- Input validation and error cases
"""

import pytest
from fastapi.testclient import TestClient

from core.db.database import DEFAULT_DB_PATH
from core.server import create_app


@pytest.fixture(scope="module")
def client():
    """Module-level test client ensuring lifespan hooks execute."""
    app = create_app(db_path=DEFAULT_DB_PATH)
    with TestClient(app) as test_client:
        yield test_client


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
