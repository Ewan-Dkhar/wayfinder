"""Lightweight micro-daemon server for Wayfinder.

Bridges the Tauri v2 transparent HUD overlay with the local SQLite FTS5 retrieval
engine and grammar-constrained SLM synthesizer.

Designed for sub-millisecond local responses, zero-crash resilience, and non-blocking
asynchronous concurrency.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running directly as 'python core/server.py'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.db.database import DEFAULT_DB_PATH
from core.llm.schemas import TacticalCard
from core.llm.synthesizer import TacticalSynthesizer

DEFAULT_HOST = os.getenv("WAYFINDER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("WAYFINDER_PORT", "8765"))


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Incoming search request from the HUD overlay."""

    query: str = Field(..., description="Player combat question or search terms", min_length=1)
    game_id: str = Field(default="sekiro", description="Target game identifier")
    encounter_id: Optional[str] = Field(default=None, description="Optional boss/encounter filter")
    source_type: Optional[str] = Field(default=None, description="Optional source filter ('youtube', 'steam', 'wiki')")


class TelemetryInfo(BaseModel):
    """Performance telemetry for latency benchmarking and source auditing."""

    query: str
    game_id: str
    retrieval_ms: float
    synthesis_ms: float
    total_ms: float
    source_type: Optional[str] = None
    fallback_used: bool = False
    error: Optional[str] = None


class QueryResponse(BaseModel):
    """Enveloped response payload delivered to the HUD."""

    found: bool
    card: Optional[TacticalCard] = None
    telemetry: TelemetryInfo
    message: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check payload for daemon and local model readiness."""

    status: str
    db_ok: bool
    slm_ok: bool
    model: str
    indexed_chunks: int


class GameSummary(BaseModel):
    """Summary of indexed combat encounters for a single game."""

    game_id: str
    encounters: List[str]
    chunk_count: int


class GamesResponse(BaseModel):
    """List of all indexed games and their available encounters."""

    games: List[GameSummary]


# -----------------------------------------------------------------------------
# Lifespan Management
# -----------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and shutdown lifecycle.
    
    Ensures persistent database connection pooling and graceful teardown
    without re-allocating connection handles per request.
    """
    db_path = getattr(app.state, "db_path", DEFAULT_DB_PATH)
    synthesizer = TacticalSynthesizer(db_path=db_path)
    app.state.synthesizer = synthesizer

    yield

    # Clean teardown
    synthesizer.close()


# -----------------------------------------------------------------------------
# FastAPI Application Factory
# -----------------------------------------------------------------------------

def create_app(db_path: Path | str = DEFAULT_DB_PATH) -> FastAPI:
    """Builds and configures the Wayfinder daemon FastAPI instance."""
    app = FastAPI(
        title="Wayfinder Daemon",
        description="Local-first in-game combat guide distillation engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.db_path = db_path

    # Permissive localhost CORS policy for Tauri v2 and Vite dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["General"])
    def root() -> Dict[str, Any]:
        """Root status route."""
        return {
            "name": "Wayfinder Daemon",
            "version": "0.1.0",
            "status": "online",
            "endpoints": ["/health", "/games", "/query"],
        }

    @app.get("/health", response_model=HealthResponse, tags=["Diagnostics"])
    def health_check(request: Request) -> HealthResponse:
        """Inspects database connectivity and local SLM daemon status."""
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer

        # Database health probe
        db_ok = False
        indexed_count = 0
        try:
            cursor = synthesizer.fts_engine.conn.execute("SELECT count(*) AS total FROM guide_chunks")
            row = cursor.fetchone()
            if row is not None:
                db_ok = True
                indexed_count = row["total"]
        except Exception:
            db_ok = False

        # Local SLM health probe
        slm_ok = synthesizer.llm_client.check_health()
        overall_status = "healthy" if (db_ok and slm_ok) else ("degraded" if db_ok else "unhealthy")

        return HealthResponse(
            status=overall_status,
            db_ok=db_ok,
            slm_ok=slm_ok,
            model=synthesizer.llm_client.model,
            indexed_chunks=indexed_count,
        )

    @app.get("/games", response_model=GamesResponse, tags=["Retrieval"])
    def list_games(request: Request) -> GamesResponse:
        """Returns all indexed games and their encounters."""
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer
        games_data = synthesizer.fts_engine.get_indexed_games()
        summaries = [
            GameSummary(
                game_id=item["game_id"],
                encounters=item["encounters"],
                chunk_count=item["chunk_count"],
            )
            for item in games_data
        ]
        return GamesResponse(games=summaries)

    @app.post("/query", response_model=QueryResponse, tags=["Combat HUD"])
    def execute_query(payload: QueryRequest, request: Request) -> QueryResponse:
        """Executes full tactical distillation: FTS5 retrieval -> SLM synthesis -> TacticalCard.
        
        Runs inside FastAPI's worker threadpool so long SLM inference does not
        block concurrent health checks or hotkey responsiveness.
        """
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer

        card, telemetry = synthesizer.query(
            player_query=payload.query,
            game_id=payload.game_id,
            encounter_id=payload.encounter_id,
            source_type=payload.source_type,
        )

        telemetry_model = TelemetryInfo(**telemetry)

        if card is None:
            return QueryResponse(
                found=False,
                card=None,
                telemetry=telemetry_model,
                message=f"No combat guides found matching '{payload.query}' for {payload.game_id}.",
            )

        return QueryResponse(
            found=True,
            card=card,
            telemetry=telemetry_model,
            message=None,
        )

    return app


# Default app instance for standard ASGI servers
app = create_app()


def main() -> None:
    """CLI runner to launch the Wayfinder micro-daemon directly."""
    parser = argparse.ArgumentParser(description="Wayfinder Micro-Daemon Server")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help=f"Host address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})")
    parser.add_argument("--reload", action="store_true", help="Enable live auto-reload for development")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print(f"🗡️  WAYFINDER DAEMON STARTING ON http://{args.host}:{args.port}")
    print(f"📡 Interactive Docs: http://{args.host}:{args.port}/docs")
    print("=" * 70 + "\n")

    uvicorn.run("core.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
