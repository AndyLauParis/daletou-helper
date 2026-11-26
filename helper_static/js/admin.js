/* 管理后台逻辑（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("admin");

  var FEEDBACK_PAGE_SIZE = 10;
  var USERS_PAGE_SIZE = 20;

  var state = {
    status: "all",
    feedbackPage: 1,
    usersPage: 1
  };

  var errorBox = document.getElementById("admin-error");
  var content = document.getElementById("admin-content");
  var denied = document.getElementById("admin-denied");
  var statsEl = document.getElementById("admin-stats");
  var feedbackList = document.getElementById("admin-feedback-list");
  var feedbackEmpty = document.getElementById("admin-feedback-empty");
  var feedbackSummary = document.getElementById("feedback-summary");
  var feedbackPageInfo = document.getElementById("feedback-page-info");
  var usersBody = document.getElementById("admin-users-body");
  var usersSummary = document.getElementById("users-summary");
  var usersPageInfo = document.getElementById("users-page-info");

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
  }

  function fmtDateTime(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    function pad(n) {
      return n < 10 ? "0" + n : String(n);
    }
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate()) +
      " " +
      pad(date.getHours()) +
      ":" +
      pad(date.getMinutes())
    );
  }

  function showDenied() {
    setIsAdmin(false);
    mountShell("admin");
    content.hidden = true;
    denied.hidden = false;
  }

  function renderStats(data) {
    var users = data.users || {};
    var expenses = data.expenses || {};
    var feedback = data.feedback || {};
    var recognition = data.recognition || {};
    var tiles = [
      { label: "注册用户", value: users.total },
      { label: "今日新增用户", value: users.today },
      { label: "管理员", value: users.admins },
      { label: "号码本总数", value: data.numbers },
      { label: "支出总额", value: fmtMoney(expenses.total) },
      { label: "本月支出", value: fmtMoney(expenses.month) },
      { label: "启用中的提醒", value: data.reminders_enabled },
      { label: "待处理反馈", value: (feedback.open || 0) + " / " + (feedback.total || 0) },
      { label: "识别记录（待审核）", value: (recognition.review || 0) + " / " + (recognition.total || 0) }
    ];
    statsEl.innerHTML = tiles
      .map(function (tile) {
        return (
          '<div class="stat"><p class="stat-label">' +
          escapeHtml(tile.label) +
          '</p><p class="stat-value">' +
          escapeHtml(tile.value === null || tile.value === undefined ? "0" : tile.value) +
          "</p></div>"
        );
      })
      .join("");
  }

  function feedbackItemHtml(item) {
    var isOpen = item.status !== "resolved";
    var statusBadge = isOpen
      ? '<span class="badge badge-warn">待处理</span>'
      : '<span class="badge badge-ok">已处理</span>';
    var shot = item.has_screenshot
      ? '<a class="feedback-shot" href="/api/helper/admin/feedback/' +
        encodeURIComponent(item.id) +
        '/screenshot" target="_blank" rel="noopener">' +
        '<img src="/api/helper/admin/feedback/' +
        encodeURIComponent(item.id) +
        '/screenshot" alt="反馈截图" loading="lazy">' +
        "</a>"
      : "";
    var action = isOpen
      ? '<button type="button" class="btn btn-ghost btn-sm" data-feedback-id="' +
        encodeURIComponent(item.id) +
        '" data-next-status="resolved">标记已处理</button>'
      : '<button type="button" class="btn btn-ghost btn-sm" data-feedback-id="' +
        encodeURIComponent(item.id) +
        '" data-next-status="open">重新打开</button>';

    return (
      '<article class="feedback-item">' +
      '<div class="feedback-item-head">' +
      '<span class="badge badge-soft">' +
      escapeHtml(item.category_label || item.category) +
      "</span>" +
      '<span class="feedback-id">#' +
      escapeHtml(item.id) +
      "</span>" +
      "<span>用户：" +
      escapeHtml(item.username || "未知") +
      "</span>" +
      statusBadge +
      '<span class="feedback-time">' +
      escapeHtml(fmtDateTime(item.created_at)) +
      "</span>" +
      "</div>" +
      '<p class="feedback-content">' +
      escapeHtml(item.content) +
      "</p>" +
      shot +
      '<div class="row-actions">' +
      action +
      "</div>" +
      "</article>"
    );
  }

  function setPager(prefix, page, pageSize, total) {
    var pages = Math.max(1, Math.ceil(total / pageSize));
    var info = document.getElementById(prefix + "-page-info");
    var prev = document.getElementById(prefix + "-prev");
    var next = document.getElementById(prefix + "-next");
    if (info) info.textContent = "第 " + page + " / " + pages + " 页 · 共 " + total + " 条";
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages;
    return pages;
  }

  async function loadOverview() {
    var data = await api("/api/helper/admin/overview");
    renderStats(data || {});
  }

  async function loadFeedback() {
    var query =
      "?status=" +
      encodeURIComponent(state.status) +
      "&page=" +
      state.feedbackPage +
      "&page_size=" +
      FEEDBACK_PAGE_SIZE;
    var data = await api("/api/helper/admin/feedback" + query);
    var items = (data && data.items) || [];
    var counts = (data && data.counts) || {};
    feedbackSummary.textContent =
      "待处理 " +
      (counts.open || 0) +
      " 条 · 已处理 " +
      (counts.resolved || 0) +
      " 条 · 共 " +
      (counts.all || 0) +
      " 条";
    feedbackList.innerHTML = items.map(feedbackItemHtml).join("");
    feedbackEmpty.hidden = items.length > 0;
    var pages = setPager(
      "feedback",
      state.feedbackPage,
      FEEDBACK_PAGE_SIZE,
      (data && data.total) || 0
    );
    if (state.feedbackPage > pages) {
      state.feedbackPage = pages;
      await loadFeedback();
    }
  }

  function userRowHtml(item) {
    var role = item.is_admin
      ? '<span class="badge badge-soft">管理员</span>'
      : '<span class="badge badge-muted">普通用户</span>';
    return (
      "<tr>" +
      "<td>" +
      escapeHtml(item.id) +
      "</td>" +
      "<td>" +
      escapeHtml(item.username) +
      "</td>" +
      "<td>" +
      role +
      "</td>" +
      "<td>" +
      escapeHtml(fmtDateTime(item.created_at)) +
      "</td>" +
      "<td>" +
      escapeHtml(item.number_count) +
      "</td>" +
      "<td>" +
      escapeHtml(item.feedback_count) +
      "</td>" +
      "</tr>"
    );
  }

  async function loadUsers() {
    var data = await api(
      "/api/helper/admin/users?page=" +
        state.usersPage +
        "&page_size=" +
        USERS_PAGE_SIZE
    );
    var items = (data && data.items) || [];
    usersSummary.textContent = "共 " + ((data && data.total) || 0) + " 个账号";
    usersBody.innerHTML = items.length
      ? items.map(userRowHtml).join("")
      : '<tr><td colspan="6">暂无注册用户</td></tr>';
    var pages = setPager(
      "users",
      state.usersPage,
      USERS_PAGE_SIZE,
      (data && data.total) || 0
    );
    if (state.usersPage > pages) {
      state.usersPage = pages;
      await loadUsers();
    }
  }

  async function refreshAll() {
    clearError();
    try {
      await loadOverview();
    } catch (err) {
      if (err.status === 403) {
        showDenied();
        return;
      }
      showError(err.message || "加载概览失败");
      return;
    }
    try {
      await Promise.all([loadFeedback(), loadUsers()]);
    } catch (err) {
      showError(err.message || "加载后台数据失败");
    }
  }

  document.getElementById("feedback-status").addEventListener("change", function (event) {
    state.status = event.target.value;
    state.feedbackPage = 1;
    loadFeedback().catch(function (err) {
      showError(err.message || "加载反馈失败");
    });
  });

  document.getElementById("feedback-refresh").addEventListener("click", function () {
    loadFeedback().catch(function (err) {
      showError(err.message || "加载反馈失败");
    });
  });

  document.getElementById("admin-refresh").addEventListener("click", refreshAll);

  document.getElementById("feedback-prev").addEventListener("click", function () {
    if (state.feedbackPage <= 1) return;
    state.feedbackPage -= 1;
    loadFeedback().catch(function (err) {
      showError(err.message || "加载反馈失败");
    });
  });

  document.getElementById("feedback-next").addEventListener("click", function () {
    state.feedbackPage += 1;
    loadFeedback().catch(function (err) {
      showError(err.message || "加载反馈失败");
    });
  });

  document.getElementById("users-prev").addEventListener("click", function () {
    if (state.usersPage <= 1) return;
    state.usersPage -= 1;
    loadUsers().catch(function (err) {
      showError(err.message || "加载用户失败");
    });
  });

  document.getElementById("users-next").addEventListener("click", function () {
    state.usersPage += 1;
    loadUsers().catch(function (err) {
      showError(err.message || "加载用户失败");
    });
  });

  feedbackList.addEventListener("click", async function (event) {
    var button =
      event.target && event.target.closest
        ? event.target.closest("[data-feedback-id]")
        : null;
    if (!button) return;
    button.disabled = true;
    clearError();
    try {
      await api("/api/helper/admin/feedback/" + button.getAttribute("data-feedback-id"), {
        method: "PATCH",
        body: JSON.stringify({ status: button.getAttribute("data-next-status") })
      });
      showToast("反馈状态已更新");
      await Promise.all([loadFeedback(), loadOverview()]);
    } catch (err) {
      showToast(err.message || "更新失败，请稍后重试");
      button.disabled = false;
    }
  });

  (async function bootstrap() {
    try {
      await loadOverview();
    } catch (err) {
      if (err.status === 403) {
        showDenied();
        return;
      }
      showError(err.message || "加载概览失败");
      return;
    }
    setIsAdmin(true);
    mountShell("admin");
    content.hidden = false;
    try {
      await Promise.all([loadFeedback(), loadUsers()]);
    } catch (err) {
      showError(err.message || "加载后台数据失败");
    }
  })();
})();
