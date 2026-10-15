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
import re
import time
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

from core.db.database import DEFAULT_DB_PATH, GuideChunk, insert_chunks_batch
from core.ingestion.chunker import chunk_cues_sliding_window
from core.ingestion.steam_parser import SteamGuideParser
from core.ingestion.transcriber import WhisperTranscriber
from core.ingestion.yt_parser import YouTubeCaptionParser
from core.llm.schemas import TacticalCard
from core.llm.synthesizer import TacticalSynthesizer

DEFAULT_HOST = os.getenv("WAYFINDER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("WAYFINDER_PORT", "8765"))


def slugify(text: str) -> str:
    """Normalizes game and encounter names into canonical identifiers."""
    clean = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", clean)


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


class ModelsResponse(BaseModel):
    """List of all discovered models in local Ollama and the current active model."""

    active_model: str
    available_models: List[str]
    ollama_connected: bool


class SetModelRequest(BaseModel):
    """Payload to update the active local SLM model."""

    model: str = Field(..., min_length=1, description="Model identifier to set as active (e.g. 'qwen2.5:1.5b')")


class SetModelResponse(BaseModel):
    """Confirmation payload after switching active model."""

    success: bool
    active_model: str
    message: str


class IngestRequest(BaseModel):
    """Payload to ingest combat guides into the local knowledge base."""

    game_id: str = Field(default="sekiro", description="Target game (e.g. 'sekiro')")
    encounter_id: str = Field(..., description="Target encounter/boss (e.g. 'guardian_ape')", min_length=1)
    source_type: str = Field(default="auto", description="'url', 'markdown', or 'auto'")
    url: Optional[str] = Field(default=None, description="YouTube, Steam Community Guide, or Wiki URL")
    content: Optional[str] = Field(default=None, description="Raw Markdown or text guide content")
    filename: Optional[str] = Field(default=None, description="Optional filename or source reference")
    window_s: float = Field(default=35.0, description="YouTube sliding window in seconds")
    stride_s: float = Field(default=15.0, description="YouTube window stride in seconds")
    force_whisper: bool = Field(default=False, description="Force Whisper CPU transcription for video")


class IngestResponse(BaseModel):
    """Result of guide ingestion and index commit."""

    success: bool
    game_id: str
    encounter_id: str
    chunks_indexed: int
    source_type: str
    source_ref: str
    latency_ms: float
    message: str


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
            "endpoints": ["/health", "/games", "/models", "/settings/model", "/query", "/ingest"],
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

    @app.get("/models", response_model=ModelsResponse, tags=["Settings"])
    def list_models(request: Request) -> ModelsResponse:
        """Discovers all models installed in local Ollama and returns the active model."""
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer
        available = synthesizer.llm_client.get_installed_models()
        is_connected = synthesizer.llm_client.check_health()
        return ModelsResponse(
            active_model=synthesizer.llm_client.model,
            available_models=available,
            ollama_connected=is_connected,
        )

    @app.post("/settings/model", response_model=SetModelResponse, tags=["Settings"])
    def set_model(payload: SetModelRequest, request: Request) -> SetModelResponse:
        """Hot-swaps the active SLM model in memory and persists to user config."""
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer
        try:
            updated = synthesizer.llm_client.set_model(payload.model, persist=True)
            return SetModelResponse(
                success=True,
                active_model=updated,
                message=f"Active model successfully switched to '{updated}'.",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to update active model: {e}",
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

    @app.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
    def ingest_guide(payload: IngestRequest, request: Request) -> IngestResponse:
        """Ingests YouTube, Steam Community, or Markdown guides into SQLite FTS5.
        
        Runs asynchronously in a threadpool so video transcription or network fetches
        do not block HUD searches or health checks.
        """
        synthesizer: TacticalSynthesizer = request.app.state.synthesizer
        conn = synthesizer.fts_engine.conn
        t_start = time.perf_counter_ns()

        clean_game = slugify(payload.game_id)
        clean_encounter = slugify(payload.encounter_id)
        if not clean_encounter:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid encounter_id: must contain valid alphanumeric characters.",
            )

        chunks: List[GuideChunk] = []
        source_type = "wiki"
        source_ref = payload.filename or f"guide_{clean_encounter}"

        # Branch A: URL Ingestion (YouTube or Steam)
        if payload.url:
            url = payload.url.strip()
            if "youtube.com" in url or "youtu.be" in url:
                source_type = "youtube"
                yt_parser = YouTubeCaptionParser()
                yt_res = yt_parser.parse(url)
                source_ref = yt_res.video_id

                cues = []
                if yt_res.has_subtitles and not payload.force_whisper:
                    cues = yt_res.cues
                else:
                    transcriber = WhisperTranscriber()
                    cues = transcriber.transcribe(url)

                raw_chunks = chunk_cues_sliding_window(
                    cues=cues,
                    window_seconds=payload.window_s,
                    stride_seconds=payload.stride_s,
                )
                chunks = [
                    GuideChunk(
                        game_id=clean_game,
                        encounter_id=clean_encounter,
                        source_type="youtube",
                        source_ref=source_ref,
                        start_time=c.start_time,
                        end_time=c.end_time,
                        content_text=c.content_text,
                    )
                    for c in raw_chunks
                ]
            elif "steamcommunity.com" in url:
                source_type = "steam"
                steam_parser = SteamGuideParser()
                steam_res = steam_parser.parse_url(url)
                source_ref = steam_res.source_id
                chunks = [
                    GuideChunk(
                        game_id=clean_game,
                        encounter_id=clean_encounter,
                        source_type="steam",
                        source_ref=source_ref,
                        start_time=0.0,
                        end_time=0.0,
                        content_text=c.content_text,
                    )
                    for c in steam_res.chunks
                ]
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported URL domain. Supported: YouTube ('youtube.com', 'youtu.be') and Steam ('steamcommunity.com').",
                )

        # Branch B: Direct Markdown or Text content
        elif payload.content:
            source_type = "wiki"
            source_ref = payload.filename or f"guide_{clean_encounter}"
            steam_parser = SteamGuideParser()
            parsed = steam_parser.parse_markdown_text(
                content=payload.content,
                source_id=source_ref,
                title=payload.encounter_id,
            )
            chunks = [
                GuideChunk(
                    game_id=clean_game,
                    encounter_id=clean_encounter,
                    source_type="wiki",
                    source_ref=source_ref,
                    start_time=0.0,
                    end_time=0.0,
                    content_text=c.content_text,
                )
                for c in parsed.chunks
            ]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either 'url' or 'content' must be provided for guide ingestion.",
            )

        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Parsed source yielded 0 combat chunks. Verify URL or Markdown formatting.",
            )

        # Commit to SQLite (Triggers automatically synchronize guide_fts table)
        inserted_count = insert_chunks_batch(conn, chunks)
        conn.commit()

        t_end = time.perf_counter_ns()
        latency_ms = (t_end - t_start) / 1_000_000.0

        return IngestResponse(
            success=True,
            game_id=clean_game,
            encounter_id=clean_encounter,
            chunks_indexed=inserted_count,
            source_type=source_type,
            source_ref=source_ref,
            latency_ms=latency_ms,
            message=f"Successfully indexed {inserted_count} combat chunks for '{clean_encounter}' in {latency_ms:.1f}ms.",
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
