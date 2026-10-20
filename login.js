const loginForm = document.getElementById("login-form");
const message = document.getElementById("message");

loginForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  message.textContent = "";

  const result = await postJson("/auth/login", {
    email: document.getElementById("gmail").value,
    password: document.getElementById("password").value,
  });

  if (!result.ok) {
    showMessage(message, errorText(result.data), "error");
    return;
  }
  localStorage.setItem("user_id", result.data.user_id);
  localStorage.setItem("user_name", result.data.name);

  window.location.href = "search.html";
});
