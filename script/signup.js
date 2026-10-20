const signupForm = document.getElementById("signup-form");
const message = document.getElementById("message");

signupForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  message.textContent = "";

  const result = await postJson("/auth/signup", {
    name: document.getElementById("name").value,
    email: document.getElementById("gmail").value, 
    phone: document.getElementById("phone").value,
    password: document.getElementById("password").value,
  });

  if (!result.ok) {
    showMessage(message, errorText(result.data), "error");
    return;
  }

  showMessage(message, "Account created! Taking you to login...", "success");
  setTimeout(function () {
    window.location.href = "login_page.html";
  }, 1000);
});
