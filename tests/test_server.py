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

