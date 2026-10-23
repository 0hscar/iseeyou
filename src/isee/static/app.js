const sidebar = document.getElementById("primary-sidebar");
const toggle = document.getElementById("sidebar-toggle");

toggle?.addEventListener("click", () => {
  const isOpen = sidebar.classList.toggle("is-open");
  toggle.setAttribute("aria-expanded", String(isOpen));
});

document.addEventListener("click", (event) => {
  if (!sidebar || !toggle || !sidebar.classList.contains("is-open")) return;
  if (sidebar.contains(event.target) || toggle.contains(event.target)) return;
  sidebar.classList.remove("is-open");
  toggle.setAttribute("aria-expanded", "false");
});

const page = document.body.dataset.page;
if (page === "overview") {
  import("./overview.js").then(({ startOverview }) => startOverview());
} else if (page === "interfaces") {
  import("./interfaces.js").then(({ startInterfaces }) => startInterfaces());
} else if (page === "connectivity") {
  import("./connectivity.js").then(({ startConnectivity }) => startConnectivity());
} else if (page === "devices") {
  import("./devices.js").then(({ startDevices }) => startDevices());
}
