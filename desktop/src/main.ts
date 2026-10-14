/**
 * Wayfinder Desktop HUD — Main TypeScript Controller
 * Pure Vanilla DOM State Controller & High-Speed API Bridge
 */

import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

// -----------------------------------------------------------------------------
// Type Definitions
// -----------------------------------------------------------------------------

interface TacticalCue {
  tell: string;
  action: string;
  outcome: string;
}

interface TacticalCard {
  game: string;
  encounter: string;
  phase_or_area: string;
  summary: string;
  tactical_cues: TacticalCue[];
  key_setup: string[];
  source_type?: string;
  source_ref?: string;
  timestamp_display?: string;
}

interface TelemetryInfo {
  query: string;
  game_id: string;
  retrieval_ms: number;
  synthesis_ms: number;
  total_ms: number;
  source_type?: string;
  fallback_used: boolean;
  error?: string;
}

interface QueryResponse {
  found: boolean;
  card?: TacticalCard;
  telemetry: TelemetryInfo;
  message?: string;
}

interface HealthResponse {
  status: string;
  db_ok: boolean;
  slm_ok: boolean;
  model: string;
  indexed_chunks: number;
}

const DAEMON_API_URL = "http://127.0.0.1:8765";

// -----------------------------------------------------------------------------
// Cached DOM Elements
// -----------------------------------------------------------------------------

let queryInput: HTMLInputElement;
let searchBtn: HTMLButtonElement;
let daemonStatus: HTMLElement;
let daemonLabel: HTMLElement;

let stateIdle: HTMLElement;
let stateLoading: HTMLElement;
let stateCard: HTMLElement;
let stateEmpty: HTMLElement;

let cardEncounter: HTMLElement;
let cardPhase: HTMLElement;
let cardSource: HTMLElement;
let cardSummary: HTMLElement;
let cuesContainer: HTMLElement;
let cardSetup: HTMLElement;
let cardTelemetry: HTMLElement;
let emptyMessage: HTMLElement;

// -----------------------------------------------------------------------------
// State Management
// -----------------------------------------------------------------------------

type HUDState = "idle" | "loading" | "card" | "empty";

function setHUDState(state: HUDState) {
  stateIdle.classList.toggle("hidden", state !== "idle");
  stateLoading.classList.toggle("hidden", state !== "loading");
  stateCard.classList.toggle("hidden", state !== "card");
  stateEmpty.classList.toggle("hidden", state !== "empty");
}

// -----------------------------------------------------------------------------
// Daemon Communication
// -----------------------------------------------------------------------------

async function checkDaemonHealth(): Promise<void> {
  try {
    const res = await fetch(`${DAEMON_API_URL}/health`, { method: "GET" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: HealthResponse = await res.json();

    daemonStatus.classList.remove("status-offline", "status-degraded", "status-online");

    if (data.status === "healthy") {
      daemonStatus.classList.add("status-online");
      daemonLabel.textContent = "ONLINE";
      daemonStatus.title = `Daemon & SLM (${data.model}) operational | ${data.indexed_chunks} chunks`;
    } else if (data.status === "degraded") {
      daemonStatus.classList.add("status-degraded");
      daemonLabel.textContent = "FALLBACK READY";
      daemonStatus.title = `Database OK (${data.indexed_chunks} chunks), local SLM offline (Deterministic fallback active)`;
    } else {
      daemonStatus.classList.add("status-offline");
      daemonLabel.textContent = "OFFLINE";
    }
  } catch {
    daemonStatus.classList.remove("status-online", "status-degraded");
    daemonStatus.classList.add("status-offline");
    daemonLabel.textContent = "NO DAEMON";
    daemonStatus.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
  }
}

async function executeSearch(query: string): Promise<void> {
  const trimmed = query.trim();
  if (!trimmed) {
    setHUDState("idle");
    return;
  }

  setHUDState("loading");

  try {
    const res = await fetch(`${DAEMON_API_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game_id: "sekiro",
        query: trimmed,
      }),
    });

    if (!res.ok) {
      throw new Error(`Search request failed with status ${res.status}`);
    }

    const data: QueryResponse = await res.json();

    if (data.found && data.card) {
      renderTacticalCard(data.card, data.telemetry);
      setHUDState("card");
    } else {
      emptyMessage.textContent = data.message || `No tactics found for '${trimmed}'.`;
      setHUDState("empty");
    }
  } catch (err: any) {
    emptyMessage.textContent = `Error reaching combat daemon: ${err?.message || err}`;
    setHUDState("empty");
  }
}

// -----------------------------------------------------------------------------
// Card Rendering (Zero Framework Direct Mutation)
// -----------------------------------------------------------------------------

function renderTacticalCard(card: TacticalCard, telemetry: TelemetryInfo): void {
  cardEncounter.textContent = card.encounter.toUpperCase();
  cardPhase.textContent = card.phase_or_area || "Combat Cue";

  // Source Badge
  const sourceLabel = card.timestamp_display
    ? `YouTube [${card.timestamp_display}]`
    : card.source_type
    ? `${card.source_type.toUpperCase()} GUIDE`
    : "VERIFIED GUIDE";
  cardSource.textContent = sourceLabel;

  cardSummary.textContent = card.summary;

  // Render 3-Bullet Combat Loop
  cuesContainer.innerHTML = "";
  card.tactical_cues.forEach((cue) => {
    const cueItem = document.createElement("div");
    cueItem.className = "cue-item";

    cueItem.innerHTML = `
      <div class="cue-row">
        <span class="tag tag-tell">TELL</span>
        <span class="cue-text">${escapeHTML(cue.tell)}</span>
      </div>
      <div class="cue-row">
        <span class="tag tag-action">ACTION</span>
        <span class="cue-text">${escapeHTML(cue.action)}</span>
      </div>
      <div class="cue-row">
        <span class="tag tag-outcome">OUTCOME</span>
        <span class="cue-text">${escapeHTML(cue.outcome)}</span>
      </div>
    `;
    cuesContainer.appendChild(cueItem);
  });

  // Key Setup Pills
  cardSetup.innerHTML = "";
  if (card.key_setup && card.key_setup.length > 0) {
    card.key_setup.forEach((item) => {
      const pill = document.createElement("span");
      pill.className = "setup-pill";
      pill.textContent = item;
      cardSetup.appendChild(pill);
    });
  }

  // Telemetry Information
  const fallbackStr = telemetry.fallback_used ? " [20ms Fallback]" : " [SLM]";
  cardTelemetry.textContent = `${telemetry.retrieval_ms.toFixed(2)}ms retrieval | ${telemetry.total_ms.toFixed(0)}ms total${fallbackStr}`;
}

function escapeHTML(str: string): string {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// -----------------------------------------------------------------------------
// Window Hiding & Focus Hand-Off
// -----------------------------------------------------------------------------

async function hideHUDWindow(): Promise<void> {
  try {
    const appWindow = getCurrentWindow();
    await appWindow.hide();
  } catch (err) {
    console.debug("Tauri window API not active (browser dev environment):", err);
  }
}

// -----------------------------------------------------------------------------
// Initialization & Event Listeners
// -----------------------------------------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
  // Bind Elements
  queryInput = document.getElementById("query-input") as HTMLInputElement;
  searchBtn = document.getElementById("search-btn") as HTMLButtonElement;
  daemonStatus = document.getElementById("daemon-status") as HTMLElement;
  daemonLabel = document.getElementById("daemon-label") as HTMLElement;

  stateIdle = document.getElementById("state-idle") as HTMLElement;
  stateLoading = document.getElementById("state-loading") as HTMLElement;
  stateCard = document.getElementById("state-card") as HTMLElement;
  stateEmpty = document.getElementById("state-empty") as HTMLElement;

  cardEncounter = document.getElementById("card-encounter") as HTMLElement;
  cardPhase = document.getElementById("card-phase") as HTMLElement;
  cardSource = document.getElementById("card-source") as HTMLElement;
  cardSummary = document.getElementById("card-summary") as HTMLElement;
  cuesContainer = document.getElementById("cues-container") as HTMLElement;
  cardSetup = document.getElementById("card-setup") as HTMLElement;
  cardTelemetry = document.getElementById("card-telemetry") as HTMLElement;
  emptyMessage = document.getElementById("empty-message") as HTMLElement;

  // Search input events
  searchBtn.addEventListener("click", () => executeSearch(queryInput.value));
  queryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      executeSearch(queryInput.value);
    } else if (e.key === "Escape") {
      hideHUDWindow();
    }
  });

  // Global ESC key listener
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideHUDWindow();
    }
  });

  // Quick hint chips
  document.querySelectorAll(".hint-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const query = chip.getAttribute("data-query");
      if (query) {
        queryInput.value = query;
        executeSearch(query);
      }
    });
  });

  // Listen for Rust Alt+G toggle event to auto-focus and select search input
  try {
    listen("focus-input", () => {
      queryInput.focus();
      queryInput.select();
    });
  } catch (err) {
    console.debug("Tauri event listener not active (browser dev environment):", err);
  }

  // Initial daemon health probe and interval check
  checkDaemonHealth();
  setInterval(checkDaemonHealth, 5000);
});

