import { connect, on } from "./ws-client.js";

const API_ORIGIN = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
const apiUrl = (path) => `${API_ORIGIN}${path}`;

const scenarioSelect = document.getElementById("scenario-select");
const btnLoadScenario = document.getElementById("btn-load-scenario");
const checkpointSelect = document.getElementById("checkpoint-interval");
const crashTargetSelect = document.getElementById("crash-target");
const btnConfig = document.getElementById("btn-config");
const btnCrash = document.getElementById("btn-crash");
const btnRecover = document.getElementById("btn-recover");
const btnAutoDemo = document.getElementById("btn-auto-demo");
const btnCheckpointFailure = document.getElementById("btn-checkpoint-failure");
const btnRecoverInterrupt = document.getElementById("btn-recover-interrupt");
const scenarioTitle = document.getElementById("scenario-title");
const scenarioExpected = document.getElementById("scenario-expected");
const stopwatchEl = document.getElementById("stopwatch");
const metricInterval = document.getElementById("metric-interval");
const metricLsn = document.getElementById("metric-lsn");
const metricIndoubt = document.getElementById("metric-indoubt");
const checkpointBanner = document.getElementById("checkpoint-banner");
const logStream = document.getElementById("log-stream");
const logCount = document.getElementById("log-count");
const timeline = document.getElementById("timeline");
const clusterState = document.getElementById("cluster-state");
const recoveryState = document.getElementById("recovery-state");

let stopwatchStart = 0;
let stopwatchTimer = null;
let logsRendered = 0;
let inDoubt = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatTime(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  const millis = Math.floor(ms % 1000).toString().padStart(3, "0");
  return `00:${minutes}:${seconds}.${millis}`;
}

function startStopwatch() {
  // The stopwatch measures user-visible RTO from crash event to completion.
  stopwatchStart = performance.now();
  clearInterval(stopwatchTimer);
  stopwatchTimer = setInterval(() => {
    stopwatchEl.textContent = formatTime(performance.now() - stopwatchStart);
  }, 40);
}

function stopStopwatch(seconds) {
  clearInterval(stopwatchTimer);
  stopwatchEl.textContent = formatTime(seconds * 1000);
}

function resetStopwatch() {
  clearInterval(stopwatchTimer);
  stopwatchStart = 0;
  stopwatchEl.textContent = "00:00:00.000";
}

function updateNodeCard(node, status, txn = 0, lsn = 0) {
  // Node cards mirror backend node_status events from the demo router.
  const card = document.getElementById(`node-${node}`);
  if (!card) return;
  card.className = `node-card status-${status}`;
  card.querySelector('[data-field="status"]').textContent = status;
  card.querySelector('[data-field="txn"]').textContent = txn;
  card.querySelector('[data-field="lsn"]').textContent = lsn;
  if (node === "A") clusterState.textContent = status;
}

function appendTimeline(text) {
  const item = document.createElement("div");
  item.className = "timeline-item mono";
  item.textContent = text;
  timeline.appendChild(item);
  timeline.scrollTop = timeline.scrollHeight;
}

function appendPhaseTimeline(event) {
  // Recovery pass events are compacted into one readable timeline line.
  const labels = {
    ANALYSIS: "Analysis",
    PARTIAL_REDO: "Partial Redo",
    GLOBAL_UNDO: "Global Undo",
  };
  const label = labels[event.pass] || event.pass || "Recovery";
  const parts = [label];
  if (typeof event.progress === "number") {
    parts.push(`progress=${Math.round(event.progress * 100)}%`);
  }
  if (event.redo_lsn !== undefined) {
    parts.push(`redo_lsn=${event.redo_lsn}`);
  }
  if (event.records_scanned !== undefined) {
    parts.push(`scanned=${event.records_scanned}`);
  }
  if (event.records_redone !== undefined) {
    parts.push(`redone=${event.records_redone}`);
  }
  if (event.records_undone !== undefined) {
    parts.push(`undone=${event.records_undone}`);
  }
  if (event.txns_redone !== undefined) {
    parts.push(`txns_redone=${event.txns_redone}`);
  }
  if (event.txns_undone !== undefined) {
    parts.push(`txns_undone=${event.txns_undone}`);
  }
  appendTimeline(parts.join(" | "));
}

function appendLog(record) {
  const line = document.createElement("div");
  line.className = `record-${record.record_type}`;
  line.textContent = `[LSN ${record.lsn}] TXN#${record.txn_id} ${record.record_type} page=${record.page_id ?? "-"} before=${record.before_image} after=${record.after_image}`;
  logStream.appendChild(line);
  logStream.scrollTop = logStream.scrollHeight;
  logsRendered += 1;
  logCount.textContent = `${logsRendered} records`;
}

function appendRecoveryLog(event) {
  const line = document.createElement("div");
  line.className = `record-RECOVERY_${event.action || "EVENT"}`;
  line.textContent = `[RECOVERY ${event.action}] LSN ${event.lsn} TXN#${event.txn_id} page=${event.page_id} apply=${event.applied_image} :: ${event.message}`;
  logStream.appendChild(line);
  logStream.scrollTop = logStream.scrollHeight;
  logsRendered += 1;
  logCount.textContent = `${logsRendered} records/events`;
}

function appendInDoubtLog(event) {
  const line = document.createElement("div");
  line.className = "record-RECOVERY_IN_DOUBT";
  line.textContent = `[IN-DOUBT] TXN#${event.txn_id} awaiting coordinator decision`;
  logStream.appendChild(line);
  logStream.scrollTop = logStream.scrollHeight;
  logsRendered += 1;
  logCount.textContent = `${logsRendered} records/events`;
}

function appendCoordinatorLog(event) {
  const line = document.createElement("div");
  line.className = `record-COORDINATOR_${event.decision || "QUERY"}`;
  line.textContent = `[COORDINATOR] TXN#${event.txn_id} ${event.decision || "QUERY"} :: ${event.message}`;
  logStream.appendChild(line);
  logStream.scrollTop = logStream.scrollHeight;
  logsRendered += 1;
  logCount.textContent = `${logsRendered} records/events`;
}

function resetDemoView(message = "") {
  resetStopwatch();
  timeline.textContent = "";
  logStream.textContent = "";
  logsRendered = 0;
  inDoubt = 0;
  logCount.textContent = "0 records";
  metricIndoubt.textContent = "0";
  checkpointBanner.textContent = "";
  checkpointBanner.classList.add("hidden");
  checkpointBanner.dataset.mode = "";
  recoveryState.textContent = "ready";
  if (message) appendTimeline(message);
}

function renderScenario(data) {
  scenarioSelect.value = data.scenario_id || scenarioSelect.value;
  scenarioTitle.textContent = data.scenario_title || "Custom configuration";
  scenarioExpected.textContent = data.scenario_expected || data.scenario_description || "";
}

async function loadRecentLog() {
  const res = await fetch(apiUrl(`/api/demo/recent-log?limit=80&_=${Date.now()}`));
  const data = await res.json();
  logStream.textContent = "";
  logsRendered = 0;
  data.records.forEach(appendLog);
}

async function loadStatus() {
  const res = await fetch(apiUrl("/api/demo/status"));
  const data = await res.json();
  renderScenario(data);
  checkpointSelect.value = data.checkpoint_interval_min;
  metricInterval.textContent = `${data.checkpoint_interval_min}m`;
  metricLsn.textContent = String(data.current_lsn || 0);
  checkpointBanner.classList.add("hidden");
  checkpointBanner.dataset.mode = "";
  if (data.checkpoint_failure_detected) {
    checkpointBanner.textContent = data.checkpoint_failure_message || "Checkpoint failure detected: falling back to the last valid END_CHECKPOINT.";
    checkpointBanner.dataset.mode = "checkpoint-failure";
    checkpointBanner.classList.remove("hidden");
  }
  if (data.recovery_interrupted) {
    checkpointBanner.textContent = data.recovery_interrupted_message || "Recovery interrupted by a second crash.";
    checkpointBanner.dataset.mode = "recovery-interrupted";
    checkpointBanner.classList.remove("hidden");
  }
  Object.entries(data.nodes).forEach(([node, status]) => {
    updateNodeCard(node, status, data.current_txn, data.current_lsn);
  });
  return data;
}

async function loadScenarios() {
  const res = await fetch(apiUrl("/api/demo/scenarios"));
  const data = await res.json();
  scenarioSelect.textContent = "";
  data.scenarios.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = scenario.title;
    option.dataset.expected = scenario.expected;
    scenarioSelect.appendChild(option);
  });
}

async function loadSelectedScenario() {
  // Loading a scenario regenerates WAL/snapshot data on the backend.
  const scenarioId = scenarioSelect.value;
  resetDemoView("loading scenario...");
  const res = await fetch(apiUrl("/api/demo/scenario"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId, seed: 42 }),
  });
  const data = await res.json();
  renderScenario(data);
  metricInterval.textContent = `${data.checkpoint_interval_min}m`;
  metricLsn.textContent = String(data.current_lsn || 0);
  await loadStatus();
  timeline.textContent = "";
  appendTimeline(`scenario loaded: ${data.scenario_title}`);
  appendTimeline(data.scenario_expected);
}

btnConfig.onclick = async () => {
  resetDemoView("applying custom config...");
  const interval = Number(checkpointSelect.value);
  const res = await fetch(apiUrl("/api/demo/config"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ checkpoint_interval_min: interval, transactions: 220, pages: 120, seed: 42 }),
  });
  const data = await res.json();
  renderScenario(data);
  metricInterval.textContent = `${interval}m`;
  metricLsn.textContent = String(data.current_lsn || 0);
  await loadStatus();
  timeline.textContent = "";
  appendTimeline("custom config loaded");
};

async function crashNode() {
  // Crash stops the backend WAL stream and freezes the current LSN.
  timeline.textContent = "";
  recoveryState.textContent = "crashed";
  const targetNode = crashTargetSelect.value;
  await fetch(apiUrl("/api/demo/crash"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_node: targetNode }),
  });
}

async function recoverNode() {
  // Recovery events are replayed through WebSocket after the backend run.
  recoveryState.textContent = "recovering";
  await fetch(apiUrl("/api/demo/recover"), { method: "POST" });
  await loadStatus();
}

async function recoverInterrupted() {
  recoveryState.textContent = "recovering";
  const res = await fetch(apiUrl("/api/demo/recover-interrupted"), { method: "POST" });
  const data = await res.json();
  if (data.recovery && data.recovery.interrupted) {
    checkpointBanner.textContent = data.recovery.message || "Recovery interrupted by a second crash.";
    checkpointBanner.dataset.mode = "recovery-interrupted";
    checkpointBanner.classList.remove("hidden");
  }
  await loadStatus();
}

async function loadScenarioById(scenarioId) {
  resetDemoView(`loading ${scenarioId}...`);
  const res = await fetch(apiUrl("/api/demo/scenario"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId, seed: 42 }),
  });
  const data = await res.json();
  renderScenario(data);
  metricInterval.textContent = `${data.checkpoint_interval_min}m`;
  await loadStatus();
  await loadRecentLog();
  timeline.textContent = "";
  appendTimeline(`scenario loaded: ${data.scenario_title}`);
  appendTimeline(data.scenario_expected);
}

btnLoadScenario.onclick = loadSelectedScenario;
btnCrash.onclick = crashNode;
btnRecover.onclick = recoverNode;
if (btnAutoDemo) {
  btnAutoDemo.onclick = async () => {
    // Optional legacy control: run a compact load -> crash -> recover flow.
    await loadSelectedScenario();
    await sleep(300);
    await crashNode();
    await sleep(300);
    await recoverNode();
  };
}
if (btnCheckpointFailure) {
  btnCheckpointFailure.onclick = async () => loadScenarioById("checkpoint_failure");
}
if (btnRecoverInterrupt) {
  btnRecoverInterrupt.onclick = recoverInterrupted;
}

on("node_status", (event) => updateNodeCard(event.node, event.status, event.txn, event.lsn));
on("log_entry", appendLog);
on("crash", (event) => {
  startStopwatch();
  const elapsed = Number(event.run_elapsed_seconds ?? 0);
  appendTimeline(`t=${elapsed.toFixed(3)}s crash injected on Node ${event.node}`);
});
on("recovery_pass", (event) => {
  appendPhaseTimeline(event);
});
on("checkpoint_failure", (event) => {
  checkpointBanner.textContent = event.message;
  checkpointBanner.dataset.mode = "checkpoint-failure";
  checkpointBanner.classList.remove("hidden");
  appendTimeline(event.message);
});
on("recovery_interrupted", (event) => {
  checkpointBanner.textContent = event.message;
  checkpointBanner.dataset.mode = "recovery-interrupted";
  checkpointBanner.classList.remove("hidden");
  recoveryState.textContent = "interrupted";
  appendTimeline(event.message);
});
on("recovery_record", (event) => {
  appendRecoveryLog(event);
});
on("in_doubt_txn", (event) => {
  inDoubt += 1;
  metricIndoubt.textContent = String(inDoubt);
  appendInDoubtLog(event);
  appendTimeline(event.message);
});
on("coordinator_query", (event) => {
  appendCoordinatorLog(event);
  appendTimeline(event.message);
});
on("coordinator_decision", (event) => {
  appendCoordinatorLog(event);
  appendTimeline(event.message);
});
on("rto_complete", (event) => {
  // Final recovery event closes the stopwatch and marks the node consistent.
  stopStopwatch(event.rto_seconds);
  recoveryState.textContent = "consistent";
  appendTimeline(`consistent; RTO=${event.rto_seconds.toFixed(6)}s`);
});

connect();
await loadScenarios();
const initialStatus = await loadStatus();
if (!initialStatus.log_stream_running) {
  await loadRecentLog();
}
