/* 账号设置页：账号信息、修改密码、数据导出与账号删除（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("settings");

  var accountName = document.getElementById("account-name");
  var accountId = document.getElementById("account-id");
  var accountError = document.getElementById("account-error");

  var passwordForm = document.getElementById("password-form");
  var oldPassword = document.getElementById("old-password");
  var newPassword = document.getElementById("new-password");
  var confirmPassword = document.getElementById("confirm-password");
  var passwordError = document.getElementById("password-error");
  var passwordStatus = document.getElementById("password-status");
  var passwordSave = document.getElementById("password-save");

  var exportBtn = document.getElementById("export-btn");
  var exportError = document.getElementById("export-error");
  var exportStatus = document.getElementById("export-status");

  var deleteForm = document.getElementById("delete-form");
  var deletePassword = document.getElementById("delete-password");
  var deleteConfirm = document.getElementById("delete-confirm");
  var deleteError = document.getElementById("delete-error");
  var deleteBtn = document.getElementById("delete-btn");

  var currentUser = null;

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function todayLocal() {
    var now = new Date();
    return now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  }

  function showError(box, message) {
    box.textContent = message;
    box.hidden = false;
  }

  function hideError(box) {
    box.hidden = true;
    box.textContent = "";
  }

  function safeFileName(name) {
    return String(name || "user").replace(/[\\/:*?"<>|\s]+/g, "_");
  }

  function loadMe() {
    return api("/api/helper/auth/me")
      .then(function (data) {
        currentUser = (data && data.user) || null;
        accountName.textContent = (currentUser && currentUser.username) || "未知用户";
        accountId.textContent = currentUser
          ? "用户 ID：" + currentUser.id
          : "";
        accountId.hidden = !currentUser;
      })
      .catch(function (err) {
        accountName.textContent = "未登录";
        showError(accountError, err.message || "加载账号信息失败");
      });
  }

  passwordForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError(passwordError);
    passwordStatus.hidden = true;

    var oldValue = oldPassword.value;
    var newValue = newPassword.value;
    if (!oldValue) {
      showError(passwordError, "请输入当前密码");
      return;
    }
    if (newValue.length < 8 || newValue.length > 128) {
      showError(passwordError, "新密码长度需为 8–128 位");
      return;
    }
    if (newValue !== confirmPassword.value) {
      showError(passwordError, "两次输入的新密码不一致");
      return;
    }

    passwordSave.disabled = true;
    api("/api/helper/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        old_password: oldValue,
        new_password: newValue
      })
    })
      .then(function () {
        clearToken();
        passwordStatus.textContent = "密码已修改，请使用新密码重新登录…";
        passwordStatus.hidden = false;
        setTimeout(function () {
          window.location.href = "/login";
        }, 1200);
      })
      .catch(function (err) {
        showError(passwordError, err.message || "修改密码失败，请稍后重试");
      })
      .finally(function () {
        passwordSave.disabled = false;
      });
  });

  exportBtn.addEventListener("click", function () {
    hideError(exportError);
    exportStatus.hidden = true;
    exportBtn.disabled = true;

    api("/api/helper/data/export")
      .then(function (data) {
        var payload = JSON.stringify(data, null, 2);
        var username =
          (currentUser && currentUser.username) ||
          (data && data.user && data.user.username) ||
          "user";
        var fileName =
          "helper-data-" +
          safeFileName(username) +
          "-" +
          todayLocal() +
          ".json";

        var blob = new Blob([payload], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () {
          URL.revokeObjectURL(url);
        }, 1000);

        var sets = (data && data.number_sets) || [];
        var expenses = (data && data.expenses) || [];
        exportStatus.textContent =
          "已导出 " +
          sets.length +
          " 条号码记录、" +
          expenses.length +
          " 条支出记录（" +
          fileName +
          "）。";
        exportStatus.hidden = false;
      })
      .catch(function (err) {
        showError(exportError, err.message || "导出数据失败，请稍后重试");
      })
      .finally(function () {
        exportBtn.disabled = false;
      });
  });

  deleteForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError(deleteError);

    var password = deletePassword.value;
    var confirmText = deleteConfirm.value.trim();
    if (!password) {
      showError(deleteError, "请输入当前密码");
      return;
    }
    if (confirmText !== "DELETE") {
      showError(deleteError, "请输入 DELETE 以确认删除账号");
      return;
    }
    if (!window.confirm("删除后号码本、预算、支出与提醒数据将无法恢复，确认永久删除账号？")) {
      return;
    }

    deleteBtn.disabled = true;
    api("/api/helper/auth/account", {
      method: "DELETE",
      body: JSON.stringify({ password: password, confirm: "DELETE" })
    })
      .then(function () {
        clearToken();
        accountName.textContent = "账号已删除";
        window.confirm("账号及全部数据已删除，即将返回注册页。");
        window.location.href = "/register";
      })
      .catch(function (err) {
        deleteBtn.disabled = false;
        showError(deleteError, err.message || "删除账号失败，请稍后重试");
      });
  });

  loadMe();
})();
