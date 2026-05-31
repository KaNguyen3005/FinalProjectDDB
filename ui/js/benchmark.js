import { connect, on } from "./ws-client.js";

const statusEl = document.getElementById("benchmark-status");
const progressBar = document.getElementById("benchmark-progress");
const tableBody = document.getElementById("summary-body");
const tableCount = document.getElementById("table-count");
const btnRun = document.getElementById("btn-run-benchmark");

const metrics = {
  intervals: document.getElementById("metric-intervals"),
  best: document.getElementById("metric-best"),
  p99: document.getElementById("metric-p99"),
  io: document.getElementById("metric-io"),
};

function asNumber(value) {
  return Number.parseFloat(value || 0);
}

function format(value) {
  return asNumber(value).toFixed(4);
}

function drawLineChart(canvas, rows) {
  // Canvas chart is generated client-side from summary.csv API rows.
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#07090d";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!rows.length) return;

  const pad = 46;
  const maxY = Math.max(...rows.flatMap((r) => [asNumber(r.mean_s), asNumber(r.median_s), asNumber(r.p99_s)]), 0.01);
  const xStep = (canvas.width - pad * 2) / Math.max(1, rows.length - 1);
  const y = (value) => canvas.height - pad - (asNumber(value) / maxY) * (canvas.height - pad * 2);
  const x = (idx) => pad + idx * xStep;

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const gy = pad + i * ((canvas.height - pad * 2) / 5);
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(canvas.width - pad, gy);
    ctx.stroke();
  }

  [
    ["mean_s", "#00ff88"],
    ["median_s", "#4da6ff"],
    ["p99_s", "#ffaa00"],
  ].forEach(([key, color]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    rows.forEach((row, idx) => {
      const px = x(idx);
      const py = y(row[key]);
      if (idx === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
  });

  ctx.fillStyle = "#8a91a3";
  ctx.font = "12px Consolas";
  rows.forEach((row, idx) => ctx.fillText(`${row.interval_min}m`, x(idx) - 12, canvas.height - 18));
}

function drawBarChart(canvas, rows) {
  // Stacked bars show how the theoretical cost model is composed.
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#07090d";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!rows.length) return;

  const pad = 42;
  const maxTotal = Math.max(...rows.map((r) => asNumber(r.io_cost) + asNumber(r.cpu_cost) + asNumber(r.comm_cost)), 1);
  const barWidth = Math.max(18, (canvas.width - pad * 2) / rows.length - 14);
  rows.forEach((row, idx) => {
    const total = asNumber(row.io_cost) + asNumber(row.cpu_cost) + asNumber(row.comm_cost);
    const x = pad + idx * ((canvas.width - pad * 2) / rows.length) + 8;
    let y = canvas.height - pad;
    [
      [asNumber(row.io_cost), "#00ff88"],
      [asNumber(row.cpu_cost), "#4da6ff"],
      [asNumber(row.comm_cost), "#ffaa00"],
    ].forEach(([value, color]) => {
      const h = (value / maxTotal) * (canvas.height - pad * 2);
      y -= h;
      ctx.fillStyle = color;
      ctx.fillRect(x, y, barWidth, h);
    });
    ctx.fillStyle = "#8a91a3";
    ctx.font = "12px Consolas";
    ctx.fillText(`${row.interval_min}m`, x, canvas.height - 18);
    ctx.fillText(total.toFixed(0), x, Math.max(16, y - 6));
  });
}

function renderTable(rows) {
  tableBody.textContent = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.interval_min}m</td>
      <td>${format(row.mean_s)}</td>
      <td>${format(row.median_s)}</td>
      <td>${format(row.p99_s)}</td>
      <td>${format(row.std_s)}</td>
      <td>${format(row.io_cost)}</td>
      <td>${format(row.cpu_cost)}</td>
      <td>${format(row.comm_cost)}</td>
      <td>${format(row.theory_rto_s)}</td>
    `;
    tableBody.appendChild(tr);
  });
  tableCount.textContent = `${rows.length} rows`;
}

async function loadResults() {
  // Refresh table, charts, and headline metrics from the latest summary.
  const res = await fetch("/api/benchmark/results");
  const rows = await res.json();
  renderTable(rows);
  drawLineChart(document.getElementById("rto-chart"), rows);
  drawBarChart(document.getElementById("cost-chart"), rows);
  metrics.intervals.textContent = String(rows.length);
  metrics.best.textContent = rows.length ? `${Math.min(...rows.map((r) => asNumber(r.mean_s))).toFixed(4)}s` : "0s";
  metrics.p99.textContent = rows.length ? `${Math.max(...rows.map((r) => asNumber(r.p99_s))).toFixed(4)}s` : "0s";
  metrics.io.textContent = rows.reduce((sum, row) => sum + asNumber(row.io_cost), 0).toFixed(1);
}

btnRun.onclick = async () => {
  // The backend runs the matrix in a background task and reports progress.
  progressBar.style.width = "0%";
  statusEl.textContent = "running full-scale matrix: 1GB WAL / 500MB snapshot";
  btnRun.disabled = true;
  await fetch("/api/benchmark/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      intervals: [1, 2, 5, 10, 20, 30],
      runs: 10,
      transactions: 300,
      pages: 250,
      seed: 42,
      txn_rate: 10.0,
      clear_existing: false,
      dataset_mode: "full_scale",
      full_scale_max_interval_min: 30,
    }),
  });
};

on("benchmark_progress", async (event) => {
  // Progress events are emitted once per completed interval/run cell.
  const completed = event.completed_runs || event.run;
  progressBar.style.width = `${Math.min(100, (completed / event.total_runs) * 100)}%`;
  statusEl.textContent = `${completed}/${event.total_runs} interval ${event.interval}m run ${event.run}: ${event.rto.toFixed(4)}s`;
  if (completed >= event.total_runs) {
    statusEl.textContent = "complete";
    btnRun.disabled = false;
    await loadResults();
  }
});

on("benchmark_error", (event) => {
  statusEl.textContent = event.message;
  btnRun.disabled = false;
});

connect();
await loadResults();
