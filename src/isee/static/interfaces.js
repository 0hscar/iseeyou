import {
  createPlot,
  formatAge,
  formatBytes,
  formatRate,
  getJSON,
  makeBadge,
  setChartEmpty,
  setError,
} from "./dashboard.js";

let interfaces = [];
let selectedName = "";
let selectedHours = 24;
let destroyPlot = null;

function renderDetails() {
  const body = document.getElementById("interface-details");
  body.replaceChildren();
  if (interfaces.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-cell";
    cell.colSpan = 6;
    cell.textContent = "No interface samples are available.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const item of interfaces) {
    const row = document.createElement("tr");
    for (const value of [item.name, item.type]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const link = document.createElement("td");
    link.append(makeBadge(item.running === null ? "unknown" : item.running ? "up" : "down", item.running === null ? "unknown" : item.running ? "available" : "unavailable"));
    const rx = document.createElement("td");
    rx.textContent = formatBytes(item.rx_bytes);
    const tx = document.createElement("td");
    tx.textContent = formatBytes(item.tx_bytes);
    const rate = document.createElement("td");
    rate.textContent = item.rate_valid
      ? `${formatRate(item.rx_bits_per_second)} RX · ${formatRate(item.tx_bits_per_second)} TX`
      : item.rate_reason?.replaceAll("_", " ") ?? "Rate unavailable";
    row.append(link, rx, tx, rate);
    body.append(row);
  }
}

function renderSelector() {
  const selector = document.getElementById("interface-select");
  const previous = selectedName;
  selector.replaceChildren();
  for (const item of interfaces) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.name;
    selector.append(option);
  }
  selector.disabled = interfaces.length === 0;
  if (interfaces.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No interface samples";
    selector.append(option);
    selectedName = "";
    return;
  }
  selectedName = interfaces.some((item) => item.name === previous) ? previous : interfaces[0].name;
  selector.value = selectedName;
}

async function renderHistory() {
  const container = document.getElementById("interface-chart");
  const empty = document.getElementById("interface-empty");
  if (destroyPlot) {
    destroyPlot();
    destroyPlot = null;
  }
  if (!selectedName) {
    setChartEmpty(container, empty, true, "No interface samples are available.");
    return;
  }
  const query = new URLSearchParams({ name: selectedName, hours: String(selectedHours) });
  const history = await getJSON(`/api/network/interfaces/history?${query}`);
  const valid = history.points.filter((point) => point.rate_valid);
  if (valid.length === 0) {
    setChartEmpty(container, empty, true, "No valid rate samples are available for this range.");
    return;
  }
  setChartEmpty(container, empty, false, "");
  const points = history.points;
  const data = [
    points.map((point) => new Date(point.sampled_at).getTime() / 1000),
    points.map((point) => point.rate_valid ? point.rx_bits_per_second : null),
    points.map((point) => point.rate_valid ? point.tx_bits_per_second : null),
  ];
  destroyPlot = createPlot(container, data, {
    scales: { x: { time: true } },
    axes: [
      { stroke: "#9aa9bc", grid: { stroke: "#29384b", width: 1 } },
      { stroke: "#9aa9bc", grid: { stroke: "#29384b", width: 1 }, values: (u, ticks) => ticks.map((value) => formatRate(value)) },
    ],
    series: [
      {},
      { label: "RX", stroke: "#61c8ff", width: 2, fill: "#61c8ff18", points: { show: false } },
      { label: "TX", stroke: "#b09aff", width: 2, fill: "#b09aff18", points: { show: false } },
    ],
    cursor: { focus: { prox: 24 } },
    legend: { show: true },
  });
}

async function refresh() {
  try {
    interfaces = await getJSON("/api/network/interfaces");
    renderDetails();
    renderSelector();
    await renderHistory();
    document.getElementById("interface-chart-note").textContent = selectedName
      ? `${selectedName} · ${selectedHours}h · latest sample ${formatAge(interfaces.find((item) => item.name === selectedName)?.sampled_at)}. Rates are averaged into chart buckets.`
      : "Rates are averaged into at most 1,000 chart buckets. Missing and invalid rates remain gaps.";
    setError("interfaces-error", null);
  } catch (error) {
    setError("interfaces-error", error);
  }
}

export function startInterfaces() {
  document.getElementById("interface-select").addEventListener("change", (event) => {
    selectedName = event.target.value;
    void refresh();
  });
  document.querySelectorAll(".range-control button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedHours = Number(button.dataset.hours);
      document.querySelectorAll(".range-control button").forEach((item) => {
        item.setAttribute("aria-pressed", String(item === button));
      });
      void refresh();
    });
  });
  void refresh();
  window.setInterval(refresh, 30000);
}
