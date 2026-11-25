/* 登录页逻辑（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("");

  var form = document.getElementById("login-form");
  var errorBox = document.getElementById("form-error");
  var submitBtn = document.getElementById("submit-btn");

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    errorBox.hidden = true;

    var username = document.getElementById("username").value.trim();
    var password = document.getElementById("password").value;

    if (!username || !password) {
      showError("请输入用户名和密码");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "登录中…";
    try {
      await api("/api/helper/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: username, password: password })
      });
      setLoggedIn(true);
      window.location.href = "/app";
    } catch (err) {
      showError(err.message || "登录失败，请稍后重试");
      submitBtn.disabled = false;
      submitBtn.textContent = "登录";
    }
  });
})();
