const params = new URLSearchParams(window.location.search);
const fromId = params.get("from");
const toId = params.get("to");
const journeyDate = params.get("date");

const trainList = document.getElementById("train-list");
const cardTemplate = document.getElementById("train-card-template");
const emptyState = document.getElementById("empty-state");
const errorMessage = document.getElementById("error-message");

function formatTime(dateTimeString) {
  if (!dateTimeString) {
    return "--:--";
  }
  const d = new Date(dateTimeString);
  const hours = String(d.getHours()).padStart(2, "0");
  const minutes = String(d.getMinutes()).padStart(2, "0");
  return hours + ":" + minutes;
}

function formatDuration(departure, arrival) {
  if (!departure || !arrival) {
    return "";
  }
  const totalMinutes = Math.round((new Date(arrival) - new Date(departure)) / 60000);
  if (totalMinutes <= 0) {
    return "";
  }
  return Math.floor(totalMinutes / 60) + "h " + (totalMinutes % 60) + "m";
}

function formatDate(dateString) {
  return new Date(dateString + "T00:00:00").toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function renderTrains(trains) {
  trainList.innerHTML = "";

  if (trains.length === 0) {
    emptyState.hidden = false;
    return;
  }

  for (const train of trains) {
    const card = cardTemplate.content.cloneNode(true);

    card.querySelector(".train-name").textContent = train.train_name;
    card.querySelector(".dep-time").textContent = formatTime(train.departure_time);
    card.querySelector(".arr-time").textContent = formatTime(train.arrival_time);
    card.querySelector(".duration").textContent =
      formatDuration(train.departure_time, train.arrival_time);

    trainList.appendChild(card);
  }
}

async function loadResults() {
  if (!fromId || !toId || !journeyDate) {
    errorMessage.textContent = "Missing search details. Please search again.";
    errorMessage.hidden = false;
    return;
  }

  document.getElementById("journey-date").textContent = formatDate(journeyDate);

  const stationsResult = await apiRequest("/stations");
  if (stationsResult.ok) {
    for (const station of stationsResult.data) {
      if (String(station.id) === fromId) {
        document.getElementById("from-name").textContent = station.name;
      }
      if (String(station.id) === toId) {
        document.getElementById("to-name").textContent = station.name;
      }
    }
  }

  const searchResult = await apiRequest(
    "/search?from_station_id=" + fromId +
    "&to_station_id=" + toId +
    "&journey_date=" + journeyDate
  );

  if (!searchResult.ok) {
    errorMessage.textContent = errorText(searchResult.data);
    errorMessage.hidden = false;
    return;
  }

  renderTrains(searchResult.data);
}

loadResults();
