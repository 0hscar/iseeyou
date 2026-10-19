export async function getJSON(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

export function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

export function setStatusText(id, value, status) {
  const element = document.getElementById(id);
  if (!element) return;
  element.className = `metric-value status-${badgeClass(status)}`;
  element.textContent = value;
}

export function setError(id, error) {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = error ? `Unable to load dashboard data: ${error.message}` : "";
  element.hidden = !error;
}

export function makeBadge(label, status) {
  const badge = document.createElement("span");
  badge.className = `badge ${badgeClass(status)}`;
  badge.textContent = label.replaceAll("_", " ");
  return badge;
}

export function badgeClass(status) {
  if (["available", "reachable", "fresh", "ok"].includes(status)) return "is-good";
  if (["degraded", "stale"].includes(status)) return "is-warn";
  if (["unavailable", "unreachable", "error"].includes(status)) return "is-bad";
  return "is-neutral";
}

export function formatRate(bitsPerSecond) {
  if (bitsPerSecond === null || bitsPerSecond === undefined) return "—";
  const units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s", "Tbit/s"];
  let value = bitsPerSecond;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)} ${units[unit]}`;
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)} ${units[unit]}`;
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function formatTime(timestamp) {
  if (!timestamp) return "Unknown";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

export function formatAge(timestamp) {
  if (!timestamp) return "No sample";
  const age = Math.max(0, (Date.now() - new Date(timestamp).getTime()) / 1000);
  if (!Number.isFinite(age)) return "Unknown age";
  if (age < 60) return `${Math.round(age)}s ago`;
  if (age < 3600) return `${Math.floor(age / 60)}m ago`;
  return `${Math.floor(age / 3600)}h ago`;
}

export function createPlot(container, data, options) {
  const Plot = window.uPlot;
  if (!Plot) throw new Error("The locally installed chart library did not load");
  const plot = new Plot(
    {
      ...options,
      width: Math.max(1, container.clientWidth),
      height: container.clientHeight || 300,
    },
    data,
    container,
  );
  const observer = new ResizeObserver(() => {
    if (container.clientWidth > 0) {
      plot.setSize({
        width: container.clientWidth,
        height: container.clientHeight || 300,
      });
    }
  });
  observer.observe(container);
  return () => {
    observer.disconnect();
    plot.destroy();
  };
}

export function setChartEmpty(container, empty, isEmpty, message) {
  empty.textContent = message;
  empty.classList.toggle("is-visible", isEmpty);
  container.hidden = isEmpty;
}
