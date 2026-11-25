/* 注册页逻辑（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("");

  var form = document.getElementById("register-form");
  var errorBox = document.getElementById("form-error");
  var submitBtn = document.getElementById("submit-btn");
  var usernameRe = /^[A-Za-z0-9_\u4e00-\u9fa5]{3,32}$/;

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    errorBox.hidden = true;

    var username = document.getElementById("username").value.trim();
    var password = document.getElementById("password").value;
    var password2 = document.getElementById("password2").value;
    var isAdult = document.getElementById("is-adult").checked;
    var inviteCode = document.getElementById("invite-code").value.trim();

    if (!usernameRe.test(username)) {
      showError("用户名需为 3–32 位字母、数字、下划线或中文");
      return;
    }
    if (password.length < 8 || password.length > 128) {
      showError("密码长度需为 8–128 位");
      return;
    }
    if (password !== password2) {
      showError("两次输入的密码不一致");
      return;
    }
    if (!isAdult) {
      showError("请先勾选“我已满 18 周岁并已阅读合规声明”");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "注册中…";
    var payload = {
      username: username,
      password: password,
      is_adult: true
    };
    if (inviteCode) payload.invite_code = inviteCode;
    try {
      await api("/api/helper/auth/register", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setLoggedIn(true);
      window.location.href = "/app";
    } catch (err) {
      showError(err.message || "注册失败，请稍后重试");
      submitBtn.disabled = false;
      submitBtn.textContent = "注册并登录";
    }
  });
})();
