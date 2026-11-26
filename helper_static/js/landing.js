/* 公开落地页：登录态切换 + 最新开奖预览（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("home");

  var PREFERRED_GAME_CODES = ["dlt", "ssq", "fc3d"];
  var PREVIEW_LIMIT = 3;
  var UNAVAILABLE_TEXT = "开奖数据暂不可用";
  var FALLBACK_TEXT = "开奖数据暂不可用，请稍后重试，或前往开奖查询页查看更多信息。";
  var MATCH_GAMES = { sfc14: true, rx9: true, jq4: true, bqc6: true };

  function applyAuthState(loggedIn) {
    setLoggedIn(loggedIn);

    var authOnly = document.querySelectorAll("[data-auth-only]");
    for (var i = 0; i < authOnly.length; i += 1) {
      authOnly[i].hidden = !loggedIn;
    }

    var guestOnly = document.querySelectorAll("[data-guest-only]");
    for (var j = 0; j < guestOnly.length; j += 1) {
      guestOnly[j].hidden = loggedIn;
    }

    /* 登录态确定后重新渲染导航，保证品牌与“首页”指向正确 */
    mountShell("home");
  }

  function collectGames(data) {
    var games = [];
    ((data && data.groups) || []).forEach(function (group) {
      (group.games || []).forEach(function (game) {
        games.push(game);
      });
    });
    return games;
  }

  function pickGames(games) {
    var picked = [];
    var used = {};

    function pick(game) {
      if (!game || game.has_adapter !== true || used[game.code]) return;
      used[game.code] = true;
      picked.push(game);
    }

    PREFERRED_GAME_CODES.forEach(function (code) {
      if (picked.length >= PREVIEW_LIMIT) return;
      for (var i = 0; i < games.length; i += 1) {
        if (games[i].code === code) {
          pick(games[i]);
          break;
        }
      }
    });

    for (var k = 0; k < games.length && picked.length < PREVIEW_LIMIT; k += 1) {
      pick(games[k]);
    }

    return picked.slice(0, PREVIEW_LIMIT);
  }

  function pad2(value) {
    var num = Number(value);
    if (!isFinite(num)) return String(value === null || value === undefined ? "" : value);
    return num < 10 ? "0" + num : String(num);
  }

  function ball(value, variant) {
    return (
      '<span class="ball' +
      (variant ? " " + variant : "") +
      '">' +
      escapeHtml(pad2(value)) +
      "</span>"
    );
  }

  function balls(values, variant) {
    var list = values || [];
    if (!list.length) return '<span class="muted small">—</span>';
    return (
      '<span class="balls">' +
      list
        .map(function (value) {
          return ball(value, variant);
        })
        .join("") +
      "</span>"
    );
  }

  function singleBall(value, variant) {
    if (value === null || value === undefined || value === "") {
      return '<span class="muted small">—</span>';
    }
    return '<span class="balls">' + ball(value, variant) + "</span>";
  }

  function numbersHtml(code, draw) {
    var numbers = (draw && draw.numbers) || {};
    if (code === "dlt") {
      return balls(numbers.front, "ball-front") + balls(numbers.back, "ball-back");
    }
    if (code === "ssq") {
      return balls(numbers.red, "ball-red") + balls(numbers.blue, "ball-blue");
    }
    if (code === "pl3" || code === "pl5" || code === "fc3d") {
      return balls(numbers.digits);
    }
    if (code === "qxc") {
      return balls(numbers.front) + singleBall(numbers.back, "ball-back");
    }
    if (code === "qlc") {
      return balls(numbers.basic, "ball-red") + singleBall(numbers.special, "ball-special");
    }
    if (code === "kl8") {
      return balls(numbers.draw, "ball-front");
    }
    if (MATCH_GAMES[code] && draw && draw.matches && draw.matches.length) {
      return (
        '<span class="muted small">共 ' +
        escapeHtml(draw.matches.length) +
        " 场赛果，请在开奖查询页查看</span>"
      );
    }
    return '<span class="muted small">—</span>';
  }

  function firstDraw(payload) {
    var draws = (payload && payload.draws) || [];
    return draws.length ? draws[0] : null;
  }

  function drawnCardHtml(game, draw) {
    var code = (game && game.code) || "";
    var name = (game && game.name) || code || "未知游戏";
    var issue = draw && draw.issue !== null && draw.issue !== undefined
      ? String(draw.issue)
      : "";
    var date = draw && draw.date ? fmtDate(draw.date) : "日期待公布";

    if (!draw) {
      return (
        '<article class="preview-card">' +
        '<div class="preview-meta"><strong>' +
        escapeHtml(name) +
        "</strong></div>" +
        '<div class="preview-numbers preview-empty">' +
        escapeHtml(UNAVAILABLE_TEXT) +
        "</div>" +
        "</article>"
      );
    }

    return (
      '<article class="preview-card">' +
      '<div class="preview-meta">' +
      "<strong>" +
      escapeHtml(name) +
      "</strong>" +
      "<span>第 " +
      escapeHtml(issue || "—") +
      " 期</span>" +
      "<span>" +
      escapeHtml(date) +
      "</span>" +
      "</div>" +
      '<div class="preview-numbers">' +
      numbersHtml(code, draw) +
      "</div>" +
      "</article>"
    );
  }

  function renderPreview(container, results) {
    var html = results
      .map(function (item) {
        return drawnCardHtml(item.game, item.draw);
      })
      .join("");
    container.innerHTML = html;
  }

  function renderFallback(container) {
    container.innerHTML =
      '<div class="preview-card preview-empty">' +
      escapeHtml(FALLBACK_TEXT) +
      "</div>";
  }

  async function loadDraws(game) {
    try {
      var payload = await api(
        "/api/helper/games/" +
          encodeURIComponent(game.code) +
          "/draws?limit=1",
        { redirectOn401: false }
      );
      return { game: game, draw: firstDraw(payload) };
    } catch (err) {
      return { game: game, draw: null };
    }
  }

  async function loadPreview() {
    var container = document.getElementById("draw-preview");
    if (!container) return;

    try {
      var data = await api("/api/helper/games", { redirectOn401: false });
      var games = pickGames(collectGames(data));
      if (!games.length) {
        renderFallback(container);
        return;
      }

      var results = await Promise.all(
        games.map(function (game) {
          return loadDraws(game);
        })
      );

      var hasDraw = results.some(function (item) {
        return Boolean(item.draw);
      });
      if (!hasDraw) {
        renderFallback(container);
        return;
      }

      renderPreview(container, results);
    } catch (err) {
      renderFallback(container);
    }
  }

  async function init() {
    try {
      var me = await api("/api/helper/auth/me", { redirectOn401: false });
      setLoggedIn(true);
      setIsAdmin(me && me.user && me.user.is_admin);
      applyAuthState(true);
    } catch (err) {
      /* 未登录（或会话失效）：保持公开访客视图，不跳转 */
      applyAuthState(false);
    }

    await loadPreview();
  }

  init().catch(function () {
    var container = document.getElementById("draw-preview");
    if (container) renderFallback(container);
  });
})();
