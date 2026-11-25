/* 游戏目录页：读取 /api/helper/games，按五类分组渲染（无框架、无外部依赖） */
(function () {
  "use strict";

  var root = document.getElementById("games-root");
  if (!root) return;

  mountShell("games");

  var WEEK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

  function scheduleText(game) {
    var days = game.schedule_weekdays;
    if (!days || !days.length) return "按赛程";
    var names = days.map(function (day) {
      var index = Number(day);
      return WEEK_LABELS[index] || "第 " + (index + 1) + " 天";
    });
    var text = names.join("、");
    if (game.draw_time) text += " " + game.draw_time;
    return text;
  }

  function dataStateText(game) {
    var status = game.data_status || {};
    var count = Number(status.draw_count) || 0;
    if (status.has_data) return "已接入 " + count + " 期";
    if (game.support_level === "catalog") return "暂无数据";
    return "接入中";
  }

  function dataStateBadge(game) {
    var status = game.data_status || {};
    if (status.has_data) {
      return '<span class="badge badge-ok">' + escapeHtml(dataStateText(game)) + "</span>";
    }
    if (game.support_level === "catalog") {
      return '<span class="badge badge-catalog">' + escapeHtml(dataStateText(game)) + "</span>";
    }
    return '<span class="badge">' + escapeHtml(dataStateText(game)) + "</span>";
  }

  function supportBadge(game) {
    if (game.support_level === "full") {
      return '<span class="badge">完整核对</span>';
    }
    return '<span class="badge badge-catalog">仅目录 + 支出</span>';
  }

  function latestText(game) {
    var status = game.data_status || {};
    if (!status.latest_issue) return "—";
    var text = "第 " + status.latest_issue + " 期";
    if (status.latest_date) text += " · " + fmtDate(status.latest_date);
    return text;
  }

  function updatedText(game) {
    var status = game.data_status || {};
    if (!status.updated_at) return "尚未同步";
    var date = new Date(status.updated_at);
    if (isNaN(date.getTime())) return "尚未同步";
    return "更新于 " + date.toLocaleString("zh-CN", { hour12: false });
  }

  function cardHtml(game) {
    var code = encodeURIComponent(game.code || "");
    var actions = "";
    if (game.support_level === "full") {
      actions =
        '<a class="btn btn-primary btn-sm" href="/static/draws.html?game=' +
        code +
        '">查看开奖</a>' +
        '<a class="btn btn-ghost btn-sm" href="/static/check.html?game=' +
        code +
        '">核对</a>';
    } else {
      actions =
        '<a class="btn btn-ghost btn-sm" href="/static/budget.html?game=' +
        code +
        '">记录支出</a>';
    }

    return (
      '<article class="game-card">' +
      '<div class="game-head">' +
      "<div>" +
      '<h3 class="game-name">' +
      escapeHtml(game.name) +
      "</h3>" +
      '<span class="game-code">' +
      escapeHtml(game.code) +
      "</span>" +
      "</div>" +
      '<div class="badges">' +
      supportBadge(game) +
      dataStateBadge(game) +
      "</div>" +
      "</div>" +
      '<dl class="game-meta">' +
      "<dt>格式</dt><dd>" +
      escapeHtml(game.format_summary) +
      "</dd>" +
      "<dt>规则</dt><dd>" +
      escapeHtml(game.rule_summary) +
      "</dd>" +
      "<dt>开奖</dt><dd>" +
      escapeHtml(scheduleText(game)) +
      "</dd>" +
      "<dt>数据</dt><dd>" +
      escapeHtml(dataStateText(game)) +
      "</dd>" +
      "<dt>更新</dt><dd>" +
      escapeHtml(updatedText(game)) +
      "</dd>" +
      "<dt>最新</dt><dd>" +
      escapeHtml(latestText(game)) +
      "</dd>" +
      "<dt>价格</dt><dd>" +
      escapeHtml(game.price_note) +
      "</dd>" +
      "</dl>" +
      '<div class="game-actions">' +
      actions +
      "</div>" +
      "</article>"
    );
  }

  function groupHtml(group) {
    var games = group.games || [];
    if (!games.length) return "";
    return (
      '<section class="game-group">' +
      '<div class="group-head">' +
      '<h2 class="group-title">' +
      escapeHtml(group.category_label) +
      "</h2>" +
      '<span class="group-count">' +
      games.length +
      " 款</span>" +
      "</div>" +
      '<div class="games-grid">' +
      games.map(cardHtml).join("") +
      "</div>" +
      "</section>"
    );
  }

  function render(data) {
    var groups = (data && data.groups) || [];
    var total = 0;
    groups.forEach(function (group) {
      total += (group.games || []).length;
    });
    if (!total) {
      root.innerHTML =
        '<div class="card state-card"><p class="muted" style="margin:0;">暂无可展示的彩票游戏。</p></div>';
      return;
    }
    root.innerHTML =
      '<div class="games-groups">' + groups.map(groupHtml).join("") + "</div>";
  }

  function showLoading() {
    root.innerHTML =
      '<div class="card state-card muted">正在加载游戏目录…</div>';
  }

  function showError(message) {
    root.innerHTML =
      '<div class="card state-card">' +
      '<div class="form-error" role="alert">' +
      escapeHtml(message || "加载游戏目录失败，请稍后重试") +
      "</div>" +
      '<button type="button" class="btn btn-primary btn-sm" id="games-retry">重新加载</button>' +
      "</div>";
    var retry = document.getElementById("games-retry");
    if (retry) retry.addEventListener("click", load);
  }

  function load() {
    showLoading();
    api("/api/helper/games")
      .then(render)
      .catch(function (err) {
        showError(err && err.message ? err.message : "加载游戏目录失败，请稍后重试");
      });
  }

  load();
})();
