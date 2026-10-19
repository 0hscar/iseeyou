import {
  formatAge,
  formatBytes,
  formatDuration,
  formatRate,
  formatTime,
  getJSON,
  makeBadge,
  setError,
  setStatusText,
  setText,
} from "./dashboard.js";

function emptyRow(message, columns) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.className = "empty-cell";
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  return row;
}

function addStackRow(container, title, detail, value, status = null) {
  const row = document.createElement("div");
  row.className = "stack-row";
  const main = document.createElement("div");
  main.className = "stack-main";
  const titleElement = document.createElement("div");
  titleElement.className = "stack-title";
  titleElement.textContent = title;
  const detailElement = document.createElement("div");
  detailElement.className = "stack-detail";
  detailElement.textContent = detail;
  main.append(titleElement, detailElement);
  const valueElement = document.createElement("div");
  valueElement.className = "stack-value";
  if (status) valueElement.append(makeBadge(status, status));
  if (value) {
    const valueText = document.createElement("span");
    valueText.textContent = value;
    valueElement.append(valueText);
  }
  row.append(main, valueElement);
  container.append(row);
}

function renderOverview(data) {
  setStatusText("router-status", data.router.status.replaceAll("_", " "), data.router.status);
  setText(
    "router-uptime",
    data.router.uptime ? `Uptime ${data.router.uptime}` : `Last sample ${formatAge(data.router.sampled_at)}`,
  );
  setText(
    "cpu-load",
    data.router.cpu_load_percent === null ? "—" : `${data.router.cpu_load_percent}%`,
  );
  const memoryUsed =
    data.router.total_memory_bytes === null || data.router.free_memory_bytes === null
      ? null
      : data.router.total_memory_bytes - data.router.free_memory_bytes;
  setText("memory-used", memoryUsed === null ? "—" : formatBytes(memoryUsed));
  setText(
    "memory-total",
    data.router.total_memory_bytes === null
      ? "No memory sample"
      : `of ${formatBytes(data.router.total_memory_bytes)}`,
  );
  setStatusText(
    "collector-status",
    data.collector_status.replaceAll("_", " "),
    data.collector_status,
  );
  setText(
    "collector-freshness",
    data.collector_last_success_at
      ? `Last success ${formatAge(data.collector_last_success_at)}`
      : "No successful collection",
  );
  setText("updated-at", `Updated ${formatTime(data.generated_at)}`);
  setText(
    "topbar-status",
    data.collector_last_success_at
      ? `Collector ${formatAge(data.collector_last_success_at)}`
      : `Collector ${data.collector_status.replaceAll("_", " ")}`,
  );

  const interfaceRows = document.getElementById("interface-rows");
  interfaceRows.replaceChildren();
  if (data.interfaces.length === 0) {
    interfaceRows.append(emptyRow("No interface samples are available.", 5));
  }
  for (const item of data.interfaces) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = item.name;
    const link = document.createElement("td");
    link.append(makeBadge(item.running === null ? "unknown" : item.running ? "up" : "down", item.running === null ? "unknown" : item.running ? "available" : "unavailable"));
    const rx = document.createElement("td");
    rx.textContent = item.rate_valid ? formatRate(item.rx_bits_per_second) : "—";
    const tx = document.createElement("td");
    tx.textContent = item.rate_valid ? formatRate(item.tx_bits_per_second) : "—";
    const freshness = document.createElement("td");
    freshness.append(makeBadge(item.freshness, item.freshness));
    row.append(name, link, rx, tx, freshness);
    interfaceRows.append(row);
  }

  const connectivityRows = document.getElementById("connectivity-rows");
  connectivityRows.replaceChildren();
  if (data.connectivity.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No connectivity targets have reported samples yet.";
    connectivityRows.append(empty);
  }
  for (const target of data.connectivity) {
    const latency =
      target.latency_ms === null ? "No successful probes" : `${target.latency_ms.toFixed(1)} ms`;
    addStackRow(
      connectivityRows,
      target.name,
      `${target.host}:${target.port} · ${formatAge(target.sampled_at)}`,
      latency,
      target.status,
    );
  }

  const outages = document.getElementById("outage-rows");
  outages.replaceChildren();
  if (data.recent_outages.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No fully failed probe periods in the last 24 hours.";
    outages.append(empty);
  }
  for (const outage of data.recent_outages) {
    const end = outage.ongoing ? "Still failing" : `Ended ${formatTime(outage.ended_at)}`;
    addStackRow(
      outages,
      outage.target_name,
      `${formatTime(outage.started_at)} · ${end}`,
      formatDuration(outage.duration_seconds),
      outage.ongoing ? "unreachable" : null,
    );
  }
}

export function startOverview() {
  const refresh = async () => {
    try {
      renderOverview(await getJSON("/api/network/overview"));
      setError("overview-error", null);
    } catch (error) {
      setError("overview-error", error);
    }
  };
  void refresh();
  window.setInterval(refresh, 30000);
}
