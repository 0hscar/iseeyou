import { formatTime, getJSON, makeBadge, setError, setText } from "./dashboard.js";

function addCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.append(cell);
}

function renderDevices(inventory) {
  const body = document.getElementById("device-rows");
  const count = inventory.devices.length;
  setText("device-count", `${count} ${count === 1 ? "device" : "devices"}`);
  setText(
    "device-updated-at",
    inventory.sampled_at ? `Sampled ${formatTime(inventory.sampled_at)}` : "Not collected yet",
  );
  const status = document.getElementById("device-inventory-status");
  status.replaceChildren(
    makeBadge(
      inventory.status === "unknown" ? "waiting for data" : inventory.status,
      inventory.status,
    ),
  );
  body.replaceChildren();
  if (count === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-cell";
    cell.colSpan = 7;
    cell.textContent =
      inventory.status === "unknown"
        ? "No successful router inventory has been collected yet."
        : "No dynamic bridge devices were learned in the latest router poll.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const device of inventory.devices) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = device.host_name || device.mac_address;
    if (device.host_name) {
      const mac = document.createElement("span");
      mac.className = "device-secondary";
      mac.textContent = device.mac_address;
      name.append(mac);
    }
    row.append(name);
    addCell(row, device.ip_addresses.length ? device.ip_addresses.join(", ") : "—");
    addCell(row, device.mac_address);
    addCell(
      row,
      device.bridge_name && device.bridge_name !== device.interface_name
        ? `${device.interface_name} (${device.bridge_name})`
        : device.interface_name,
    );
    addCell(row, device.vlan_id === null ? "—" : String(device.vlan_id));
    addCell(row, device.bridge_age || "—");
    addCell(row, device.dhcp_server || "—");
    body.append(row);
  }
}

export function startDevices() {
  const refresh = async () => {
    try {
      renderDevices(await getJSON("/api/network/devices"));
      setError("devices-error", null);
    } catch (error) {
      setError("devices-error", error);
    }
  };
  void refresh();
  window.setInterval(refresh, 30000);
}
