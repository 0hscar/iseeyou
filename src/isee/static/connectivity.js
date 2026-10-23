import {
  createPlot,
  formatAge,
  formatDuration,
  formatTime,
  getJSON,
  makeBadge,
  setChartEmpty,
  setError,
} from "./dashboard.js";

let targets = [];
let selectedName = "";
let selectedHours = 24;
let destroyPlot = null;

function renderTargets() {
  const container = document.getElementById("connectivity-targets");
  const selector = document.getElementById("target-select");
  container.replaceChildren();
  selector.replaceChildren();
  if (targets.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No connectivity targets have reported samples.";
    container.append(empty);
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No target samples";
    selector.append(option);
    selector.disabled = true;
    selectedName = "";
    return;
  }
  selector.disabled = false;
  for (const target of targets) {
    const card = document.createElement("article");
    card.className = "target-card";
    const heading = document.createElement("div");
    heading.className = "target-card-heading";
    const name = document.createElement("h3");
    name.textContent = target.name;
    heading.append(name, makeBadge(target.status, target.status));
    const address = document.createElement("p");
    address.className = "target-address";
    address.textContent = `${target.host}:${target.port} · ${formatAge(target.sampled_at)}`;
    const metrics = document.createElement("div");
    metrics.className = "target-metrics";
    const latency = document.createElement("div");
    const latencyLabel = document.createElement("div");
    latencyLabel.className = "target-metric-label";
    latencyLabel.textContent = "TCP latency";
    const latencyValue = document.createElement("div");
    latencyValue.className = "target-metric-value";
    latencyValue.textContent = target.latency_ms === null ? "—" : `${target.latency_ms.toFixed(1)} ms`;
    latency.append(latencyLabel, latencyValue);
    const failure = document.createElement("div");
    const failureLabel = document.createElement("div");
    failureLabel.className = "target-metric-label";
    failureLabel.textContent = "Probe failures";
    const failureValue = document.createElement("div");
    failureValue.className = "target-metric-value";
    failureValue.textContent = `${target.probe_failure_percent.toFixed(1)}%`;
    failure.append(failureLabel, failureValue);
    metrics.append(latency, failure);
    card.append(heading, address, metrics);
    container.append(card);

    const option = document.createElement("option");
    option.value = target.name;
    option.textContent = target.name;
    selector.append(option);
  }
  if (!targets.some((target) => target.name === selectedName)) {
    selectedName = targets[0].name;
  }
  selector.value = selectedName;
}

async function renderOutages() {
  const container = document.getElementById("connectivity-outages");
  container.replaceChildren();
  if (!selectedName) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Select a target to view its recent fully failed probe periods.";
    container.append(empty);
    return;
  }
  const query = new URLSearchParams({ name: selectedName, hours: String(selectedHours) });
  const outages = await getJSON(`/api/network/connectivity/outages?${query}`);
  if (outages.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = `No fully failed probe periods for ${selectedName} in this range.`;
    container.append(empty);
    return;
  }
  for (const outage of outages) {
    const row = document.createElement("div");
    row.className = "stack-row";
    const main = document.createElement("div");
    main.className = "stack-main";
    const title = document.createElement("div");
    title.className = "stack-title";
    title.textContent = outage.ongoing ? "Still unreachable" : "Unreachable period";
    const detail = document.createElement("div");
    detail.className = "stack-detail";
    detail.textContent = `${formatTime(outage.started_at)} · ${outage.ongoing ? "Ongoing" : `Ended ${formatTime(outage.ended_at)}`}`;
    const duration = document.createElement("div");
    duration.className = "stack-value";
    duration.textContent = formatDuration(outage.duration_seconds);
    main.append(title, detail);
    row.append(main, duration);
    container.append(row);
  }
}

async function renderHistory() {
  const container = document.getElementById("connectivity-chart");
  const empty = document.getElementById("connectivity-empty");
  if (destroyPlot) {
    destroyPlot();
    destroyPlot = null;
  }
  if (!selectedName) {
    setChartEmpty(container, empty, true, "No connectivity target samples are available.");
    return;
  }
  const query = new URLSearchParams({ name: selectedName, hours: String(selectedHours) });
  const history = await getJSON(`/api/network/connectivity/history?${query}`);
  if (history.points.length === 0) {
    setChartEmpty(container, empty, true, "No connectivity samples are available for this range.");
    return;
  }
  setChartEmpty(container, empty, false, "");
  const points = history.points;
  const data = [
    points.map((point) => new Date(point.sampled_at).getTime() / 1000),
    points.map((point) => point.latency_ms),
    points.map((point) => point.probe_failure_percent),
  ];
  destroyPlot = createPlot(container, data, {
    scales: { x: { time: true }, y: { auto: true }, y2: { auto: true, range: [0, 100] } },
    axes: [
      { stroke: "#9aa9bc", grid: { stroke: "#29384b", width: 1 } },
      { scale: "y", stroke: "#9aa9bc", grid: { stroke: "#29384b", width: 1 }, label: "Latency (ms)" },
      { scale: "y2", side: 1, stroke: "#9aa9bc", grid: { show: false }, label: "Failures (%)", values: (u, ticks) => ticks.map((value) => `${value}%`) },
    ],
    series: [
      {},
      { label: "TCP latency", scale: "y", stroke: "#68d5a1", width: 2, points: { show: false } },
      { label: "Failed probes", scale: "y2", stroke: "#ff8888", width: 2, points: { show: false } },
    ],
    cursor: { focus: { prox: 24 } },
    legend: { show: true },
  });
}

async function refresh() {
  try {
    targets = await getJSON("/api/network/connectivity");
    renderTargets();
    await Promise.all([renderHistory(), renderOutages()]);
    setError("connectivity-error", null);
  } catch (error) {
    setError("connectivity-error", error);
  }
}

export function startConnectivity() {
  document.getElementById("target-select").addEventListener("change", (event) => {
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
