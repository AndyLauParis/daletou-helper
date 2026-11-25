/* 开奖查询页：按游戏读取开奖/赛果缓存并格式化展示（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("draws");

  var gameSelect = document.getElementById("game-select");
  var refreshBtn = document.getElementById("refresh-btn");
  var reloadBtn = document.getElementById("reload-btn");
  var statusLine = document.getElementById("status-line");
  var errorBox = document.getElementById("error-box");
  var root = document.getElementById("draws-root");

  var games = [];
  var currentCode = "dlt";
  var loading = false;

  var MATCH_GAMES = { sfc14: true, rx9: true, jq4: true, bqc6: true };

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function hideError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }

  function queryGame() {
    try {
      var value = new URLSearchParams(window.location.search).get("game");
      return (value || "").trim().toLowerCase();
    } catch (err) {
      return "";
    }
  }

  function pad2(value) {
    var num = Number(value);
    if (!isFinite(num)) return String(value);
    return num < 10 ? "0" + num : String(num);
  }

  function ball(value, cls) {
    return (
      '<span class="ball ' + (cls || "") + '">' + escapeHtml(pad2(value)) + "</span>"
    );
  }

  function balls(values, cls) {
    var list = values || [];
    if (!list.length) return '<span class="muted small">—</span>';
    return (
      '<span class="balls">' +
      list
        .map(function (value) {
          return ball(value, cls);
        })
        .join("") +
      "</span>"
    );
  }

  function digits(values) {
    var list = values || [];
    if (!list.length) return '<span class="muted small">—</span>';
    return (
      '<span class="digits-line">' +
      list
        .map(function (value) {
          return '<span class="digit">' + escapeHtml(pad2(value)) + "</span>";
        })
        .join("") +
      "</span>"
    );
  }

  function labeled(label, html) {
    return (
      '<div class="number-group"><span class="number-label">' +
      escapeHtml(label) +
      "</span>" +
      html +
      "</div>"
    );
  }

  function resultPill(value) {
    var text = value === null || value === undefined || value === "" ? "待定" : String(value);
    return '<span class="result-pill">' + escapeHtml(text) + "</span>";
  }

  function matchTable(code, draw) {
    var matches = draw.matches || [];
    if (!matches.length) {
      return '<p class="muted small" style="margin:0;">赛果待公布或暂不可用。</p>';
    }
    var showHalf = code === "bqc6";
    var head =
      "<tr><th>场次</th><th>主队</th><th>客队</th><th>比分</th>" +
      (showHalf ? "<th>半场</th>" : "") +
      "<th>赛果</th></tr>";
    var rows = matches
      .map(function (match) {
        var score = match.score ? escapeHtml(match.score) : "—";
        return (
          "<tr><td>" +
          escapeHtml(match.index) +
          "</td><td>" +
          escapeHtml(match.home || "—") +
          "</td><td>" +
          escapeHtml(match.away || "—") +
          "</td><td>" +
          score +
          "</td>" +
          (showHalf ? "<td>" + resultPill(match.half_result) + "</td>" : "") +
          "<td>" +
          resultPill(match.result) +
          "</td></tr>"
        );
      })
      .join("");
    return (
      '<div class="table-wrap"><table class="match-table"><thead>' +
      head +
      "</thead><tbody>" +
      rows +
      "</tbody></table></div>"
    );
  }

  function numbersHtml(code, draw) {
    var numbers = draw.numbers || {};
    if (code === "dlt") {
      return (
        labeled("前区", balls(numbers.front, "ball-front")) +
        labeled("后区", balls(numbers.back, "ball-back"))
      );
    }
    if (code === "ssq") {
      return (
        labeled("红球", balls(numbers.red, "ball-red")) +
        labeled("蓝球", balls(numbers.blue, "ball-blue"))
      );
    }
    if (code === "pl3" || code === "pl5" || code === "fc3d") {
      return labeled("号码", digits(numbers.digits));
    }
    if (code === "qxc") {
      var back =
        numbers.back === null || numbers.back === undefined
          ? '<span class="muted small">—</span>'
          : balls([numbers.back], "ball-back");
      return labeled("前区", digits(numbers.front)) + labeled("后区", back);
    }
    if (code === "qlc") {
      var special =
        numbers.special === null || numbers.special === undefined
          ? '<span class="muted small">—</span>'
          : balls([numbers.special], "ball-special");
      return labeled("基本号", balls(numbers.basic, "ball-red")) + labeled("特别号", special);
    }
    if (code === "kl8") {
      return (
        '<div class="ball-grid">' +
        (numbers.draw || [])
          .map(function (value) {
            return ball(value, "ball-front");
          })
          .join("") +
        "</div>"
      );
    }
    if (MATCH_GAMES[code]) {
      return matchTable(code, draw);
    }
    return (
      '<pre class="payload">' +
      escapeHtml(JSON.stringify(numbers || {}, null, 2)) +
      "</pre>"
    );
  }

  function drawHtml(code, draw) {
    var issue = String(draw.issue || "");
    var link =
      "/static/check.html?game=" +
      encodeURIComponent(code) +
      "&issue=" +
      encodeURIComponent(issue);
    return (
      '<article class="draw-item">' +
      '<div class="draw-head">' +
      "<div>" +
      '<span class="draw-issue">第 ' +
      escapeHtml(issue) +
      " 期</span>" +
      '<span class="draw-date">' +
      escapeHtml(draw.date || "日期待公布") +
      "</span>" +
      "</div>" +
      '<a class="btn btn-ghost btn-sm" href="' +
      link +
      '">核对这期</a>' +
      "</div>" +
      numbersHtml(code, draw) +
      "</article>"
    );
  }

  function setStatus(text) {
    statusLine.textContent = text;
  }

  function render(data) {
    var game = (data && data.game) || {};
    var code = game.code || currentCode;
    var status = (data && data.status) || "";
    var source = data && data.source ? data.source : "暂无数据源";
    var updated = data && data.updated_at ? fmtDate(data.updated_at) : "—";

    setStatus(
      (game.name || code) +
        " · 数据源：" +
        source +
        " · 更新时间：" +
        updated
    );

    if (status === "catalog_only") {
      root.innerHTML =
        '<div class="empty">' +
        "该游戏仅提供目录与支出记录，不提供开奖数据或核对。" +
        '<div class="row-actions" style="justify-content:center;margin-top:12px;">' +
        '<a class="btn btn-ghost btn-sm" href="/static/budget.html?game=' +
        encodeURIComponent(code) +
        '">记录支出</a>' +
        '<a class="btn btn-ghost btn-sm" href="/static/games.html">返回游戏目录</a>' +
        "</div></div>";
      return;
    }

    var draws = (data && data.draws) || [];
    if (!draws.length) {
      root.innerHTML =
        '<div class="empty">' +
        escapeHtml((data && data.notice) || "暂无开奖数据，可点击“刷新数据”重试。") +
        "</div>";
      return;
    }

    var notice = data && data.notice
      ? '<div class="notice notice-info">' + escapeHtml(data.notice) + "</div>"
      : "";

    root.innerHTML =
      notice +
      '<div class="draw-list">' +
      draws
        .map(function (draw) {
          return drawHtml(code, draw);
        })
        .join("") +
      "</div>";
  }

  function loadDraws() {
    if (!currentCode) return Promise.resolve();
    loading = true;
    hideError();
    root.innerHTML = '<div class="empty">正在加载开奖数据…</div>';
    setStatus("正在加载开奖数据…");

    return api(
      "/api/helper/games/" +
        encodeURIComponent(currentCode) +
        "/draws?limit=30&refresh=false"
    )
      .then(render)
      .catch(function (err) {
        root.innerHTML = '<div class="empty">开奖数据加载失败。</div>';
        setStatus("加载失败");
        showError(err && err.message ? err.message : "加载开奖数据失败，请稍后重试");
      })
      .finally(function () {
        loading = false;
      });
  }

  function refreshDraws() {
    if (!currentCode || loading) return;
    refreshBtn.disabled = true;
    hideError();
    setStatus("正在刷新数据…");
    api("/api/helper/games/" + encodeURIComponent(currentCode) + "/refresh", {
      method: "POST"
    })
      .then(function (data) {
        if (data && data.ok === false) {
          showError(data.message || "刷新失败，已保留上次缓存");
        }
        return loadDraws();
      })
      .catch(function (err) {
        showError(err && err.message ? err.message : "刷新失败，请稍后重试");
      })
      .finally(function () {
        refreshBtn.disabled = false;
      });
  }

  function fillGames() {
    gameSelect.innerHTML = games
      .map(function (game) {
        return (
          '<option value="' +
          escapeHtml(game.code) +
          '">' +
          escapeHtml(game.name + "（" + game.category_label + "）") +
          "</option>"
        );
      })
      .join("");
    gameSelect.disabled = !games.length;
  }

  function loadGames() {
    return api("/api/helper/games")
      .then(function (data) {
        games = [];
        ((data && data.groups) || []).forEach(function (group) {
          (group.games || []).forEach(function (game) {
            games.push(game);
          });
        });
        fillGames();
        var wanted = queryGame();
        var known = games.some(function (game) {
          return game.code === wanted;
        });
        currentCode = known ? wanted : "dlt";
        gameSelect.value = currentCode;
        if (!games.some(function (game) {
          return game.code === "dlt";
        }) && games.length) {
          currentCode = games[0].code;
          gameSelect.value = currentCode;
        }
        return loadDraws();
      })
      .catch(function (err) {
        gameSelect.disabled = true;
        root.innerHTML = '<div class="empty">游戏目录加载失败。</div>';
        setStatus("游戏目录加载失败");
        showError(err && err.message ? err.message : "加载游戏目录失败，请稍后重试");
      });
  }

  function syncQuery() {
    try {
      var url = "?game=" + encodeURIComponent(currentCode);
      window.history.replaceState(null, "", url);
    } catch (err) {
      /* 忽略不支持 history 的环境 */
    }
  }

  gameSelect.addEventListener("change", function () {
    currentCode = gameSelect.value;
    syncQuery();
    loadDraws();
  });

  refreshBtn.addEventListener("click", refreshDraws);

  reloadBtn.addEventListener("click", function () {
    if (!games.length) {
      loadGames();
    } else {
      loadDraws();
    }
  });

  loadGames();
})();
