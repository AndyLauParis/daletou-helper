/* 首页逻辑（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("home");

  var nameEl = document.getElementById("account-name");
  var errorBox = document.getElementById("load-error");
  var logoutBtn = document.getElementById("logout-btn");
  var banner = document.getElementById("upcoming-banner");

  logoutBtn.addEventListener("click", async function () {
    logoutBtn.disabled = true;
    try {
      await api("/api/helper/auth/logout", { method: "POST" });
    } catch (err) {
      /* 会话失效时也执行本地退出 */
    }
    setLoggedIn(false);
    window.location.href = "/login";
  });

  api("/api/helper/auth/me")
    .then(function (data) {
      nameEl.textContent = (data && data.user && data.user.username) || "未知用户";
      setLoggedIn(true);
    })
    .catch(function (err) {
      nameEl.textContent = "未登录";
      errorBox.textContent = err.message || "加载账号信息失败";
      errorBox.hidden = false;
    });

  api("/api/helper/reminders/upcoming")
    .then(function (items) {
      if (!items || !items.length) return;
      banner.innerHTML = items
        .map(function (item) {
          return (
            '<div class="notice notice-info banner">' +
            escapeHtml(item.message || item.game_name + " 即将开奖") +
            ' <a class="banner-link" href="/static/reminders.html">查看提醒</a>' +
            "</div>"
          );
        })
        .join("");
    })
    .catch(function () {
      /* 提醒横幅失败时静默，不影响首页 */
    });
})();
