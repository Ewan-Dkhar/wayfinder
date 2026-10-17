/**
 * Wayfinder Desktop HUD — Main TypeScript Controller
 * Pure Vanilla DOM State Controller & High-Speed API Bridge
 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

// -----------------------------------------------------------------------------
// Type Definitions
// -----------------------------------------------------------------------------

interface TacticalCue {
  tell: string;
  action: string;
  outcome: string;
  clip_url?: string;
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
  clip_url?: string;
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

interface IngestResponse {
  success: boolean;
  game_id: string;
  encounter_id: string;
  chunks_indexed: number;
  source_type: string;
  source_ref: string;
  latency_ms: number;
  message: string;
}

interface GameSummary {
  game_id: string;
  encounters: string[];
  chunk_count: number;
}

interface GamesResponse {
  games: GameSummary[];
}

interface ModelsResponse {
  active_model: string;
  available_models: string[];
  ollama_connected: boolean;
}

interface SetModelResponse {
  success: boolean;
  active_model: string;
  message: string;
}

const DAEMON_API_URL = "http://127.0.0.1:8765";

// -----------------------------------------------------------------------------
// Cached DOM Elements & Active State
// -----------------------------------------------------------------------------

let activeGameId: string = "";
let wasDaemonOnline: boolean = false;

let queryInput: HTMLInputElement;
let searchBtn: HTMLButtonElement;
let gameSelect: HTMLSelectElement;
let modelSelect: HTMLSelectElement;
let btnQuitApp: HTMLButtonElement;
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

// Ingestion Elements
let ingestModal: HTMLElement;
let btnOpenIngest: HTMLButtonElement;
let btnCloseIngest: HTMLButtonElement;
let btnCancelIngest: HTMLButtonElement;
let btnSubmitIngest: HTMLButtonElement;
let btnSubmitText: HTMLElement;
let ingestGame: HTMLInputElement;
let ingestBoss: HTMLInputElement;
let tabUrl: HTMLButtonElement;
let tabFile: HTMLButtonElement;
let panelUrl: HTMLElement;
let panelFile: HTMLElement;
let ingestUrl: HTMLInputElement;
let dropzone: HTMLElement;
let dropzoneText: HTMLElement;
let fileInput: HTMLInputElement;
let ingestContent: HTMLTextAreaElement;
let ingestFeedback: HTMLElement;
let ingestExtractClips: HTMLInputElement;

let activeIngestTab: "url" | "file" = "url";
let selectedFileName: string | null = null;

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

    const isNowOnline = data.status === "healthy" || data.status === "degraded";
    if (isNowOnline && !wasDaemonOnline) {
      wasDaemonOnline = true;
      fetchGamesCatalog();
      fetchModelsCatalog();
    }

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
    wasDaemonOnline = false;
    daemonStatus.classList.remove("status-online", "status-degraded");
    daemonStatus.classList.add("status-offline");
    daemonLabel.textContent = "NO DAEMON";
    daemonStatus.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";

    if (!activeGameId && gameSelect) {
      gameSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
      gameSelect.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
    }
    if (modelSelect && (!modelSelect.value || modelSelect.value === "connecting")) {
      modelSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
      modelSelect.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
    }
  }
}

async function fetchGamesCatalog(selectGameId?: string): Promise<void> {
  try {
    const res = await fetch(`${DAEMON_API_URL}/games`, { method: "GET" });
    if (!res.ok) {
      gameSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
      gameSelect.title = "Could not fetch games catalog: daemon returned an error";
      activeGameId = "";
      return;
    }
    const data: GamesResponse = await res.json();
    if (!data.games || data.games.length === 0) {
      gameSelect.innerHTML = '<option value="" disabled selected>NO GUIDES</option>';
      gameSelect.title = "No combat guides indexed yet. Click '📥 Ingest' to index your first guide.";
      activeGameId = "";
      return;
    }

    gameSelect.innerHTML = "";
    data.games.forEach((g) => {
      const opt = document.createElement("option");
      opt.value = g.game_id;
      opt.textContent = g.game_id.replace(/[_-]/g, " ").toUpperCase();
      gameSelect.appendChild(opt);
    });

    if (selectGameId && data.games.some((g) => g.game_id === selectGameId)) {
      activeGameId = selectGameId;
    } else if (!data.games.some((g) => g.game_id === activeGameId)) {
      activeGameId = data.games[0].game_id;
    }

    gameSelect.value = activeGameId;
    gameSelect.title = `Switch active game (Current: ${activeGameId.toUpperCase()})`;
  } catch (err) {
    console.debug("Could not fetch games catalog:", err);
    gameSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
    gameSelect.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
    activeGameId = "";
  }
}

async function fetchModelsCatalog(): Promise<void> {
  try {
    const res = await fetch(`${DAEMON_API_URL}/models`, { method: "GET" });
    if (!res.ok) {
      modelSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
      modelSelect.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
      return;
    }
    const data: ModelsResponse = await res.json();
    if (!data.available_models || data.available_models.length === 0) {
      const fallbackModel = data.active_model || "fallback";
      modelSelect.innerHTML = `<option value="${fallbackModel}" selected>NO SLM (FALLBACK)</option>`;
      modelSelect.title = "Ollama is offline or no models found. Tactical synthesis will use deterministic fallback.";
      return;
    }

    modelSelect.innerHTML = "";
    data.available_models.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name.replace(/^library\//, "");
      modelSelect.appendChild(opt);
    });

    modelSelect.value = data.active_model;
    if (!data.ollama_connected) {
      modelSelect.title = `Ollama offline - deterministic fallback active (${data.active_model})`;
    } else {
      modelSelect.title = `Active local SLM: ${data.active_model}`;
    }
  } catch (err) {
    console.debug("Could not fetch models catalog:", err);
    modelSelect.innerHTML = '<option value="" disabled selected>NO DAEMON</option>';
    modelSelect.title = "Could not connect to Wayfinder micro-daemon at http://127.0.0.1:8765";
  }
}

async function switchActiveModel(newModel: string): Promise<void> {
  try {
    const res = await fetch(`${DAEMON_API_URL}/settings/model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: newModel }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: SetModelResponse = await res.json();
    console.info("Active model switched to:", data.active_model);
    modelSelect.title = `Active local SLM: ${data.active_model}`;
    await checkDaemonHealth();
  } catch (err) {
    console.error("Failed to switch model:", err);
  }
}

async function executeSearch(query: string): Promise<void> {
  const trimmed = query.trim();
  if (!trimmed) {
    setHUDState("idle");
    return;
  }

  if (!activeGameId) {
    emptyMessage.textContent = "No combat guides indexed yet. Click '📥 Ingest' above to add your first YouTube, Steam, or Markdown guide!";
    setHUDState("empty");
    return;
  }

  setHUDState("loading");

  try {
    const res = await fetch(`${DAEMON_API_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game_id: activeGameId,
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

  // Render 3-Bullet Combat Loop with optional visual micro-clip
  cuesContainer.innerHTML = "";
  card.tactical_cues.forEach((cue, index) => {
    const cueItem = document.createElement("div");
    cueItem.className = "cue-item";

    // Associate clip: individual cue clip_url, or fallback to top card clip_url for the first cue
    const clipUrl = cue.clip_url || (index === 0 ? card.clip_url : undefined);

    const clipHtml = clipUrl
      ? `
        <div class="cue-clip-box" title="Combat Telegraph Loop (Click to pause/play, ⛶ for theatre view)">
          <video class="cue-video" src="${DAEMON_API_URL}${clipUrl}" autoplay loop muted playsinline preload="auto"></video>
          <span class="clip-pill">▶ LOOP</span>
          <button class="clip-expand-btn" title="Expand to theatre view">⛶</button>
        </div>
      `
      : "";

    cueItem.innerHTML = `
      <div class="cue-content-wrap ${clipUrl ? "has-clip" : ""}">
        <div class="cue-rows">
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
        </div>
        ${clipHtml}
      </div>
    `;

    // Click on clip to toggle play/pause or expand to theatre view
    if (clipUrl) {
      const videoEl = cueItem.querySelector(".cue-video") as HTMLVideoElement | null;
      const clipBox = cueItem.querySelector(".cue-clip-box") as HTMLElement | null;
      const expandBtn = cueItem.querySelector(".clip-expand-btn") as HTMLButtonElement | null;

      if (videoEl && clipBox) {
        expandBtn?.addEventListener("click", (e) => {
          e.stopPropagation();
          clipBox.classList.toggle("expanded");
        });

        clipBox.addEventListener("click", (e) => {
          e.stopPropagation();
          if (clipBox.classList.contains("expanded")) {
            clipBox.classList.remove("expanded");
            return;
          }
          if (videoEl.paused) {
            videoEl.play();
            clipBox.classList.remove("paused");
          } else {
            videoEl.pause();
            clipBox.classList.add("paused");
          }
        });
      }
    }

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
// Ingestion Modal Management
// -----------------------------------------------------------------------------

function openIngestModal(): void {
  ingestModal.classList.remove("hidden");
  ingestFeedback.classList.add("hidden");
  ingestFeedback.textContent = "";

  if (activeGameId && !ingestGame.value.trim()) {
    ingestGame.value = activeGameId;
  }

  if (ingestGame.value.trim()) {
    ingestBoss.focus();
  } else {
    ingestGame.focus();
  }
}

function closeIngestModal(): void {
  ingestModal.classList.add("hidden");
  queryInput.focus();
}

function switchIngestTab(tab: "url" | "file"): void {
  activeIngestTab = tab;
  tabUrl.classList.toggle("active", tab === "url");
  tabFile.classList.toggle("active", tab === "file");
  panelUrl.classList.toggle("hidden", tab !== "url");
  panelFile.classList.toggle("hidden", tab !== "file");
}

async function handleFileSelected(file: File): Promise<void> {
  selectedFileName = file.name;
  dropzoneText.innerHTML = `Selected: <strong>${escapeHTML(file.name)}</strong> (${(file.size / 1024).toFixed(1)} KB)`;

  try {
    const text = await file.text();
    ingestContent.value = text;

    // Auto-fill boss name if empty
    if (!ingestBoss.value.trim()) {
      const cleanName = file.name.replace(/\.[^/.]+$/, "").replace(/[_-]/g, " ");
      ingestBoss.value = cleanName;
    }
  } catch (err: any) {
    showIngestFeedback(`Failed to read file: ${err?.message || err}`, "error");
  }
}

function showIngestFeedback(message: string, type: "success" | "error" | "loading"): void {
  ingestFeedback.className = `ingest-feedback ${type}`;
  ingestFeedback.textContent = message;
  ingestFeedback.classList.remove("hidden");
}

function inferMetadataFromUrl(url: string): { game?: string; encounter?: string } {
  try {
    const parsed = new URL(url.trim());
    const hostname = parsed.hostname.toLowerCase();
    const pathname = decodeURIComponent(parsed.pathname).replace(/^\/+|\/+$/g, "");
    let game = "";
    let encounter = "";

    if (hostname.includes("fextralife.com")) {
      const sub = hostname.split(".")[0];
      if (sub && sub !== "wiki" && sub !== "www") game = sub;
    } else if (hostname.includes("fandom.com") || hostname.includes("wiki.gg")) {
      const sub = hostname.split(".")[0];
      if (sub && sub !== "www") game = sub;
    }

    if (pathname) {
      const parts = pathname.split("/").filter((p) => !["wiki", "guides", "guide", "index.php"].includes(p.toLowerCase()));
      if (parts.length > 0) {
        encounter = parts[parts.length - 1].replace(/[+_-]+/g, " ").trim();
      }
    }
    return { game, encounter };
  } catch {
    return {};
  }
}

async function executeIngest(): Promise<void> {
  let gameId = ingestGame.value.trim() || activeGameId;
  let encounterId = ingestBoss.value.trim();

  if (activeIngestTab === "url") {
    const url = ingestUrl.value.trim();
    if (!url) {
      showIngestFeedback("Please enter a valid YouTube, Steam, or Wiki URL.", "error");
      ingestUrl.focus();
      return;
    }

    // Auto-infer metadata if fields were left empty
    const inferred = inferMetadataFromUrl(url);
    if (!gameId && inferred.game) gameId = inferred.game;
    if (!encounterId && inferred.encounter) encounterId = inferred.encounter;
  }

  if (!gameId && activeIngestTab !== "url") {
    showIngestFeedback("Game identifier is required (e.g. sekiro, elden_ring).", "error");
    ingestGame.focus();
    return;
  }

  if (!encounterId && activeIngestTab !== "url") {
    showIngestFeedback("Boss or Encounter name is required.", "error");
    ingestBoss.focus();
    return;
  }

  const payload: any = {
    game_id: gameId || undefined,
    encounter_id: encounterId || undefined,
  };

  if (activeIngestTab === "url") {
    payload.url = ingestUrl.value.trim();
    payload.source_type = "url";
    payload.extract_clips = ingestExtractClips ? ingestExtractClips.checked : true;
  } else {
    const content = ingestContent.value.trim();
    if (!content) {
      showIngestFeedback("Please upload a .md file or paste guide text.", "error");
      ingestContent.focus();
      return;
    }
    payload.content = content;
    payload.source_type = "markdown";
    payload.filename = selectedFileName || `${encounterId}_guide.md`;
  }

  // Set loading state
  btnSubmitIngest.disabled = true;
  btnSubmitText.textContent = "Indexing...";
  showIngestFeedback("Parsing and indexing combat chunks into SQLite FTS5...", "loading");

  try {
    const res = await fetch(`${DAEMON_API_URL}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data: IngestResponse = await res.json();

    if (!res.ok) {
      throw new Error(data.message || `Ingest failed with status ${res.status}`);
    }

    showIngestFeedback(`✅ ${data.message}`, "success");
    checkDaemonHealth();
    await fetchGamesCatalog(data.game_id);

    // Auto-fill search with the newly indexed encounter and close modal after 1.2s
    setTimeout(() => {
      queryInput.value = encounterId;
      closeIngestModal();
      executeSearch(encounterId);
    }, 1200);

  } catch (err: any) {
    showIngestFeedback(`❌ ${err?.message || err}`, "error");
  } finally {
    btnSubmitIngest.disabled = false;
    btnSubmitText.textContent = "Index Combat Intel";
  }
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

async function quitApplication(): Promise<void> {
  try {
    await invoke("exit_app");
  } catch {
    try {
      const appWindow = getCurrentWindow();
      await appWindow.close();
    } catch (err) {
      console.debug("Could not exit app via Tauri window API:", err);
    }
  }
}

// -----------------------------------------------------------------------------
// Initialization & Event Listeners
// -----------------------------------------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
  // Bind Search & HUD Elements
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

  // Bind Game Selector
  gameSelect = document.getElementById("game-select") as HTMLSelectElement;
  gameSelect.addEventListener("change", () => {
    activeGameId = gameSelect.value;
    ingestGame.value = activeGameId;
    if (queryInput.value.trim()) {
      executeSearch(queryInput.value);
    }
  });

  // Bind Model Selector
  modelSelect = document.getElementById("model-select") as HTMLSelectElement;
  modelSelect.addEventListener("change", () => {
    switchActiveModel(modelSelect.value);
  });

  // Bind Quit Application Button
  btnQuitApp = document.getElementById("btn-quit-app") as HTMLButtonElement;
  btnQuitApp?.addEventListener("click", () => {
    quitApplication();
  });

  // Bind Ingestion Elements
  ingestModal = document.getElementById("ingest-modal") as HTMLElement;
  btnOpenIngest = document.getElementById("btn-open-ingest") as HTMLButtonElement;
  btnCloseIngest = document.getElementById("btn-close-ingest") as HTMLButtonElement;
  btnCancelIngest = document.getElementById("btn-cancel-ingest") as HTMLButtonElement;
  btnSubmitIngest = document.getElementById("btn-submit-ingest") as HTMLButtonElement;
  btnSubmitText = document.getElementById("btn-submit-text") as HTMLElement;
  ingestGame = document.getElementById("ingest-game") as HTMLInputElement;
  ingestBoss = document.getElementById("ingest-boss") as HTMLInputElement;
  tabUrl = document.getElementById("tab-url") as HTMLButtonElement;
  tabFile = document.getElementById("tab-file") as HTMLButtonElement;
  panelUrl = document.getElementById("panel-url") as HTMLElement;
  panelFile = document.getElementById("panel-file") as HTMLElement;
  ingestUrl = document.getElementById("ingest-url") as HTMLInputElement;
  dropzone = document.getElementById("dropzone") as HTMLElement;
  dropzoneText = document.getElementById("dropzone-text") as HTMLElement;
  fileInput = document.getElementById("file-input") as HTMLInputElement;
  ingestContent = document.getElementById("ingest-content") as HTMLTextAreaElement;
  ingestFeedback = document.getElementById("ingest-feedback") as HTMLElement;
  ingestExtractClips = document.getElementById("ingest-extract-clips") as HTMLInputElement;

  // Search input events
  searchBtn.addEventListener("click", () => executeSearch(queryInput.value));
  queryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      executeSearch(queryInput.value);
    } else if (e.key === "Escape") {
      hideHUDWindow();
    }
  });

  // Global ESC key listener (closes expanded clip first, then modal, else hides HUD)
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const expandedClip = document.querySelector(".cue-clip-box.expanded");
      if (expandedClip) {
        expandedClip.classList.remove("expanded");
        return;
      }
      if (!ingestModal.classList.contains("hidden")) {
        closeIngestModal();
      } else {
        hideHUDWindow();
      }
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

  // Ingestion Modal Listeners
  btnOpenIngest.addEventListener("click", openIngestModal);
  btnCloseIngest.addEventListener("click", closeIngestModal);
  btnCancelIngest.addEventListener("click", closeIngestModal);
  tabUrl.addEventListener("click", () => switchIngestTab("url"));
  tabFile.addEventListener("click", () => switchIngestTab("file"));
  btnSubmitIngest.addEventListener("click", executeIngest);

  // Auto-fill Game / Encounter when pasting a Wiki URL
  ingestUrl.addEventListener("input", () => {
    const url = ingestUrl.value.trim();
    if (url) {
      const inferred = inferMetadataFromUrl(url);
      if (inferred.game && (!ingestGame.value.trim() || ingestGame.value === "sekiro")) {
        ingestGame.value = inferred.game;
      }
      if (inferred.encounter && !ingestBoss.value.trim()) {
        ingestBoss.value = inferred.encounter;
      }
    }
  });

  // File Dropzone Handling
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) {
      handleFileSelected(fileInput.files[0]);
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("drag-over");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
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

  // Initial daemon health probe, catalogs load, and interval check
  checkDaemonHealth();
  fetchGamesCatalog();
  fetchModelsCatalog();
  setInterval(checkDaemonHealth, 5000);
});

