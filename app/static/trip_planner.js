// Trip planner: add legs, look up direct trains per leg, then submit the
// whole trip as one form post (Feature 7). No framework, just the DOM.

let legCount = 0;

function addLeg() {
  const template = document.getElementById("leg-template");
  const clone = template.content.cloneNode(true);
  const card = clone.querySelector(".leg");
  legCount += 1;
  card.dataset.legIndex = legCount;
  card.querySelector("h3").textContent = `Leg ${legCount}`;

  card.querySelector(".find-trains").addEventListener("click", () => onFindTrains(card));
  card.querySelector(".remove-leg").addEventListener("click", () => card.remove());

  document.getElementById("legs").appendChild(clone);
}

async function onFindTrains(card) {
  const from = card.querySelector(".leg-from").value;
  const to = card.querySelector(".leg-to").value;
  const date = card.querySelector(".leg-date").value;
  const optionsDiv = card.querySelector(".train-options");

  if (!date) {
    optionsDiv.innerHTML = '<p class="error">Pick a date first.</p>';
    return;
  }
  if (from === to) {
    optionsDiv.innerHTML = '<p class="error">From and To must differ.</p>';
    return;
  }

  optionsDiv.innerHTML = "<p>Searching…</p>";
  const url = `/trip-planner/search-leg?from_station_id=${from}&to_station_id=${to}&journey_date=${date}`;
  const res = await fetch(url);
  const trains = await res.json();

  if (trains.length === 0) {
    optionsDiv.innerHTML = '<p class="error">No direct train with a free seat for this leg.</p>';
    return;
  }

  const legIndex = card.dataset.legIndex;
  optionsDiv.innerHTML = trains
    .map(
      (t, i) => `
      <label>
        <input type="radio" name="train-choice-${legIndex}" value="${t.train_id}" ${i === 0 ? "checked" : ""}>
        ${t.name} (${t.number}) — ${t.departure_time} → ${t.arrival_time}
      </label>`
    )
    .join("");
}

function buildHiddenFields(event) {
  const hiddenContainer = document.getElementById("hidden-fields");
  hiddenContainer.innerHTML = "";

  const legs = document.querySelectorAll(".leg");
  let missing = false;

  legs.forEach((card) => {
    const legIndex = card.dataset.legIndex;
    const selected = card.querySelector(`input[name="train-choice-${legIndex}"]:checked`);
    if (!selected) {
      missing = true;
      return;
    }
    const fields = {
      leg_train_id: selected.value,
      leg_from: card.querySelector(".leg-from").value,
      leg_to: card.querySelector(".leg-to").value,
      leg_date: card.querySelector(".leg-date").value,
      leg_ticket_type: card.querySelector(".leg-ticket-type").value,
    };
    for (const [name, value] of Object.entries(fields)) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      hiddenContainer.appendChild(input);
    }
  });

  if (legs.length === 0 || missing) {
    event.preventDefault();
    alert("Add at least one leg and pick a train for each before booking.");
  }
}

document.getElementById("add-leg").addEventListener("click", addLeg);
document.getElementById("trip-form").addEventListener("submit", buildHiddenFields);

// start with one leg pre-added
addLeg();
