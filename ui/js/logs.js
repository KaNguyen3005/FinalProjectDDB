const nodeFilter = document.getElementById("node-filter");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnRefresh = document.getElementById("btn-refresh");
const pageState = document.getElementById("page-state");
const recordTotal = document.getElementById("record-total");
const recordsBody = document.getElementById("records-body");

let offset = 0;
const limit = 50;

function cell(value) {
  return value === null || value === undefined ? "-" : value;
}

async function loadRecords() {
  const params = new URLSearchParams({ offset, limit });
  if (nodeFilter.value) params.set("node", nodeFilter.value);
  const res = await fetch(`/api/logs/records?${params}`);
  const data = await res.json();
  recordsBody.textContent = "";
  data.records.forEach((record) => {
    const tr = document.createElement("tr");
    tr.className = `record-${record.record_type}`;
    tr.innerHTML = `
      <td>${record.lsn}</td>
      <td>${record.node}</td>
      <td>${record.txn_id}</td>
      <td>${record.record_type}</td>
      <td>${cell(record.page_id)}</td>
      <td>${record.before_image}</td>
      <td>${record.after_image}</td>
      <td>${record.redo_lsn}</td>
    `;
    recordsBody.appendChild(tr);
  });
  recordTotal.textContent = `${data.total} total`;
  pageState.textContent = `offset ${offset}`;
}

btnPrev.onclick = async () => {
  offset = Math.max(0, offset - limit);
  await loadRecords();
};

btnNext.onclick = async () => {
  offset += limit;
  await loadRecords();
};

btnRefresh.onclick = loadRecords;
nodeFilter.onchange = async () => {
  offset = 0;
  await loadRecords();
};

await loadRecords();
