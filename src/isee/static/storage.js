const rows = document.getElementById("storage-month-rows");
const message = document.getElementById("storage-message");
const deleteBefore = document.getElementById("storage-delete-before");
const deleteButton = document.getElementById("storage-delete-button");

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(1)} ${units[unit]}`;
}

function monthEnd(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Date(Date.UTC(year, monthNumber, 0)).toISOString().slice(0, 10);
}

function showMessage(text, isError = false) {
  message.hidden = !text;
  message.textContent = text;
  message.classList.toggle("storage-success", !isError && Boolean(text));
}

async function loadStorage() {
  const response = await fetch("/api/storage/usage", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Storage request failed (${response.status}).`);
  const usage = await response.json();

  document.getElementById("storage-database-size").textContent = formatBytes(usage.database_bytes);
  document.getElementById("storage-month-count").textContent = String(usage.months.length);
  deleteBefore.max = usage.protected_before;
  deleteBefore.value = usage.protected_before;
  deleteButton.disabled = false;

  if (usage.months.length === 0) {
    rows.innerHTML = '<tr><td class="empty-cell" colspan="6">No collection history is stored yet.</td></tr>';
    return;
  }

  rows.replaceChildren(...usage.months.map((month) => {
    const row = document.createElement("tr");
    const values = [
      month.month,
      month.runs.toLocaleString(),
      month.interface_samples.toLocaleString(),
      month.connectivity_samples.toLocaleString(),
      formatBytes(month.estimated_payload_bytes),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }

    const actionCell = document.createElement("td");
    const exportLink = document.createElement("a");
    exportLink.className = "action-link";
    exportLink.textContent = "Download .jsonl.gz";
    exportLink.href = `/api/storage/export?from=${encodeURIComponent(`${month.month}-01`)}&through=${encodeURIComponent(monthEnd(month.month))}`;
    actionCell.append(exportLink);
    row.append(actionCell);
    return row;
  }));
}

deleteButton.addEventListener("click", async () => {
  const before = deleteBefore.value;
  if (!before) {
    showMessage("Choose a date before continuing.", true);
    return;
  }
  if (!window.confirm(`Permanently delete stored collection history before ${before} UTC? Export anything you want to keep first.`)) {
    return;
  }

  deleteButton.disabled = true;
  showMessage("Deleting old history and reclaiming database space…");
  try {
    const response = await fetch("/api/storage/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ before, confirmation: "DELETE" }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `Deletion failed (${response.status}).`);
    }
    const reclaimed = Math.max(0, result.database_bytes_before - result.database_bytes_after);
    showMessage(
      `Deleted ${result.deleted_runs.toLocaleString()} collection runs and reclaimed ${formatBytes(reclaimed)}.`,
    );
    await loadStorage();
  } catch (error) {
    showMessage(error.message || "Could not delete old history.", true);
  } finally {
    deleteButton.disabled = false;
  }
});

loadStorage().catch((error) => {
  rows.innerHTML = '<tr><td class="empty-cell" colspan="6">Storage information could not be loaded.</td></tr>';
  showMessage(error.message || "Could not load storage information.", true);
});
