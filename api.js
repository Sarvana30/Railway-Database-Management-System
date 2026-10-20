const BASE_URL = "http://127.0.0.1:8000";

async function apiRequest(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE_URL + path, options);
  } catch (error) {
    return {
      ok: false,
      data: { detail: "Cannot reach the server. Check that the backend is running." },
    };
  }

  try {
    const data = await res.json();
    return { ok: res.ok, data: data };
  } catch (error) {
    return {
      ok: false,
      data: { detail: "The server returned an error (status " + res.status + "). Check the backend terminal." },
    };
  }
}

function postJson(path, body) {
  return apiRequest(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function errorText(data) {
  if (typeof data.detail === "string") {
    return data.detail;
  }
  return "Please check the details you entered.";
}

function showMessage(element, text, type) {
  element.textContent = text;
  element.className = "message " + type;
}
