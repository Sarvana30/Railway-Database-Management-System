const fromSelect = document.getElementById("from");
const toSelect = document.getElementById("to");
const dateInput = document.getElementById("date");
const searchForm = document.getElementById("search-form");
const message = document.getElementById("message");

const now = new Date();
const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  .toISOString()
  .split("T")[0];
dateInput.min = today;
dateInput.value = today;
async function loadStations() {
  const result = await apiRequest("/stations");

  if (!result.ok) {
    showMessage(message, errorText(result.data), "error");
    return;
  }

  for (const station of result.data) {
    const label = station.name + " (" + station.city + ")";
    fromSelect.add(new Option(label, station.id));
    toSelect.add(new Option(label, station.id));
  }
}

searchForm.addEventListener("submit", function (event) {
  event.preventDefault();

  if (fromSelect.value === toSelect.value) {
    showMessage(message, "From and To stations must be different.", "error");
    return;
  }

  window.location.href =
    "results.html?from=" + fromSelect.value +
    "&to=" + toSelect.value +
    "&date=" + dateInput.value;
});

loadStations();
