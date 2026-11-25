/* 开奖提醒页：多游戏提醒设置、下期开奖时间与站内 upcoming 横幅（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("reminders");

  var upcomingRoot = document.getElementById("upcoming-root");
  var remindersRoot = document.getElementById("reminders-root");
  var listError = document.getElementById("list-error");
  var notifyBtn = document.getElementById("notify-btn");
  var notifyStatus = document.getElementById("notify-status");

  var upcomingItems = [];

  function showError(message) {
    listError.textContent = message;
    listError.hidden = false;
  }

  function hideError() {
    listError.hidden = true;
    listError.textContent = "";
  }

  function reminderHtml(item) {
    var nextText = item.next_draw_text || "—";
    var noteHtml = item.note
      ? '<p class="hint">' + escapeHtml(item.note) + "</p>"
      : "";
    var badge = item.note ? '<span class="badge badge-muted">按赛程</span>' : "";

    return (
      '<article class="reminder-item" data-code="' +
      escapeHtml(item.game_code) +
      '">' +
      '<div class="reminder-head">' +
      "<div>" +
      '<h3 class="item-title">' +
      escapeHtml(item.game_name) +
      " " +
      badge +
      "</h3>" +
      '<p class="item-sub">' +
      escapeHtml(item.category_label) +
      " · " +
      escapeHtml(item.game_code) +
      "</p>" +
      "</div>" +
      "</div>" +
      '<dl class="reminder-meta">' +
      "<dt>开奖</dt><dd>" +
      escapeHtml(item.schedule_text) +
      "</dd>" +
      "<dt>下期</dt><dd data-role=\"next\">" +
      escapeHtml(nextText) +
      "</dd>" +
      "</dl>" +
      noteHtml +
      '<div class="reminder-controls">' +
      '<label class="check-inline"><input type="checkbox" data-role="enabled"' +
      (item.enabled ? " checked" : "") +
      ">开启提醒</label>" +
      '<label class="check-inline">提前 <input class="lead-input" type="number" min="5" max="180" step="1" data-role="lead" value="' +
      Number(item.lead_minutes) +
      '"> 分钟</label>' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="save">保存</button>' +
      '<span class="muted small" data-role="status"></span>' +
      "</div>" +
      "</article>"
    );
  }

  function renderReminders(items) {
    if (!items.length) {
      remindersRoot.innerHTML = '<div class="empty">暂无可设置提醒的游戏。</div>';
      return;
    }
    remindersRoot.innerHTML =
      '<div class="reminder-list">' + items.map(reminderHtml).join("") + "</div>";
  }

  function loadReminders() {
    hideError();
    remindersRoot.innerHTML = '<div class="empty">正在加载提醒设置…</div>';
    return api("/api/helper/reminders")
      .then(renderReminders)
      .catch(function (err) {
        remindersRoot.innerHTML = '<div class="empty">提醒设置加载失败。</div>';
        showError(err.message || "加载提醒设置失败，请稍后重试");
      });
  }

  function renderUpcoming(items) {
    upcomingItems = items || [];
    if (!upcomingItems.length) {
      upcomingRoot.innerHTML =
        '<div class="card empty" style="margin:0;">当前没有进入提醒窗口的开奖。已启用的游戏会在开奖前按设置的提前时间出现在这里。</div>';
      return;
    }
    upcomingRoot.innerHTML =
      '<div class="notice notice-info">' +
      "<strong>即将开奖</strong>" +
      '<ul class="upcoming-list">' +
      upcomingItems
        .map(function (item) {
          return "<li>" + escapeHtml(item.message) + "</li>";
        })
        .join("") +
      "</ul>" +
      "</div>";
  }

  function loadUpcoming() {
    return api("/api/helper/reminders/upcoming")
      .then(renderUpcoming)
      .catch(function (err) {
        upcomingRoot.innerHTML =
          '<div class="card empty" style="margin:0;">站内提醒暂时无法加载，稍后刷新即可。</div>';
        if (err && err.message) showError(err.message);
      });
  }

  function setNotifyStatus(text) {
    notifyStatus.textContent = text;
  }

  function notifyUpcoming() {
    if (!upcomingItems.length || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    upcomingItems.slice(0, 3).forEach(function (item) {
      try {
        new Notification("开奖提醒", { body: item.message, tag: item.game_code });
      } catch (err) {
        /* 部分浏览器不支持直接构造通知，站内横幅仍然可用 */
      }
    });
  }

  function setupNotify() {
    if (!("Notification" in window)) {
      notifyBtn.hidden = true;
      setNotifyStatus("当前浏览器不支持系统通知，站内提醒仍然可用。");
      return;
    }
    if (Notification.permission === "granted") {
      notifyBtn.textContent = "浏览器通知已授权";
      notifyBtn.disabled = true;
      setNotifyStatus("已授权浏览器通知，可在站内提醒基础上收到系统通知。");
      return;
    }
    if (Notification.permission === "denied") {
      notifyBtn.hidden = true;
      setNotifyStatus("浏览器通知已被拒绝，可在浏览器设置中重新开启；站内提醒仍然可用。");
      return;
    }

    notifyBtn.addEventListener("click", function () {
      notifyBtn.disabled = true;
      var request;
      try {
        request = Notification.requestPermission();
      } catch (err) {
        notifyBtn.disabled = false;
        setNotifyStatus("无法申请通知权限，站内提醒仍然可用。");
        return;
      }
      Promise.resolve(request)
        .then(function (permission) {
          if (permission === "granted") {
            notifyBtn.textContent = "浏览器通知已授权";
            setNotifyStatus("已授权浏览器通知，可在站内提醒基础上收到系统通知。");
            notifyUpcoming();
          } else {
            notifyBtn.disabled = false;
            setNotifyStatus("未获得通知权限，站内提醒仍然可用。");
          }
        })
        .catch(function () {
          notifyBtn.disabled = false;
          setNotifyStatus("无法申请通知权限，站内提醒仍然可用。");
        });
    });
  }

  remindersRoot.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action='save']");
    if (!button) return;
    var card = button.closest("[data-code]");
    if (!card) return;
    var code = card.getAttribute("data-code");
    var enabledInput = card.querySelector("[data-role='enabled']");
    var leadInput = card.querySelector("[data-role='lead']");
    var status = card.querySelector("[data-role='status']");
    var lead = Number(leadInput.value);

    hideError();
    status.textContent = "";
    if (!isFinite(lead) || lead < 5 || lead > 180 || Math.floor(lead) !== lead) {
      status.textContent = "提前分钟需为 5–180 的整数";
      status.style.color = "var(--danger)";
      return;
    }

    button.disabled = true;
    api("/api/helper/reminders/" + encodeURIComponent(code), {
      method: "PUT",
      body: JSON.stringify({ enabled: enabledInput.checked, lead_minutes: lead })
    })
      .then(function (item) {
        var nextCell = card.querySelector("[data-role='next']");
        if (nextCell) nextCell.textContent = item.next_draw_text || "—";
        status.textContent = item.enabled ? "已开启" : "已关闭";
        status.style.color = "var(--muted)";
        loadUpcoming();
      })
      .catch(function (err) {
        status.textContent = err.message || "保存失败";
        status.style.color = "var(--danger)";
      })
      .finally(function () {
        button.disabled = false;
      });
  });

  setupNotify();
  loadReminders();
  loadUpcoming();
})();
