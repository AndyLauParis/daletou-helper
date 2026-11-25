/* 兑奖核对页：按游戏动态生成表单，提交 /api/helper/check 并展示核对明细 */
(function () {
  "use strict";

  mountShell("draws");

  var gameSelect = document.getElementById("game-select");
  var issueHint = document.getElementById("issue-hint");
  var form = document.getElementById("check-form");
  var fields = document.getElementById("fields");
  var formError = document.getElementById("form-error");
  var submitBtn = document.getElementById("submit-btn");
  var resetBtn = document.getElementById("reset-btn");
  var resultCard = document.getElementById("result-card");
  var resultRoot = document.getElementById("result-root");

  var games = [];
  var currentCode = "dlt";

  var DETAIL_LABELS = {
    front: "前区",
    back: "后区",
    digits: "号码",
    draw_digits: "开奖号码",
    red_hits: "红球命中",
    blue_hit: "蓝球命中",
    front_hits: "前区命中",
    back_hits: "后区命中",
    hits: "命中个数",
    total: "总场次",
    wrong_indexes: "未命中场次",
    prize_amount: "参考奖金",
    prize_note: "奖金说明",
    play_type: "玩法",
    tier: "奖级编码",
    basic_hits: "基本号命中",
    special_hit: "特别号命中",
    pick_count: "选号个数",
    issue: "期号",
    reason: "原因",
    matches: "逐场明细",
    errors: "错误"
  };

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  function hideError() {
    formError.hidden = true;
    formError.textContent = "";
  }

  function hideResult() {
    resultCard.hidden = true;
    resultRoot.innerHTML = "";
  }

  function query(name) {
    try {
      return (new URLSearchParams(window.location.search).get(name) || "").trim();
    } catch (err) {
      return "";
    }
  }

  function splitSides(text) {
    var raw = String(text || "")
      .replace(/＋/g, "+")
      .replace(/[；;|]/g, "+");
    var index = raw.indexOf("+");
    if (index >= 0) return [raw.slice(0, index), raw.slice(index + 1)];
    return [raw, ""];
  }

  function parseNumbers(text) {
    var tokens = String(text || "").match(/\d+/g) || [];
    return tokens.map(function (token) {
      return Number(token);
    });
  }

  function parseDigits(text, count) {
    var compact = String(text || "").replace(/[\s,，、]/g, "");
    if (new RegExp("^\\d{" + count + "}$").test(compact)) {
      return compact.split("").map(Number);
    }
    return parseNumbers(text);
  }

  function parseTwoSide(text, frontCount, backCount) {
    var sides = splitSides(text);
    if (sides[1].trim()) {
      return { front: parseNumbers(sides[0]), back: parseNumbers(sides[1]) };
    }
    var all = parseNumbers(text);
    return {
      front: all.slice(0, frontCount),
      back: all.slice(frontCount, frontCount + backCount)
    };
  }

  function parseQxc(text) {
    var raw = String(text || "").trim();
    var sides = splitSides(raw);
    if (sides[1].trim()) {
      return { front: parseNumbers(sides[0]).slice(0, 6), back: parseNumbers(sides[1])[0] };
    }
    var compact = raw.replace(/[\s,，、]/g, "");
    if (/^\d{7,8}$/.test(compact)) {
      return {
        front: compact.slice(0, 6).split("").map(Number),
        back: Number(compact.slice(6))
      };
    }
    var all = parseNumbers(raw);
    return { front: all.slice(0, 6), back: all[6] };
  }

  function valueOf(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : "";
  }

  function textField(id, label, placeholder, hint) {
    return (
      '<div class="field"><label for="' +
      id +
      '">' +
      escapeHtml(label) +
      '</label><input id="' +
      id +
      '" type="text" autocomplete="off" spellcheck="false" placeholder="' +
      escapeHtml(placeholder) +
      '">' +
      (hint ? '<p class="hint">' + escapeHtml(hint) + "</p>" : "") +
      "</div>"
    );
  }

  function playTypeField(options) {
    return (
      '<div class="field"><label for="play-type">玩法</label><select id="play-type">' +
      options
        .map(function (item) {
          return '<option value="' + escapeHtml(item.value) + '">' + escapeHtml(item.label) + "</option>";
        })
        .join("") +
      "</select></div>"
    );
  }

  function pickTable(count, options, selectable, hint) {
    var rows = "";
    for (var index = 1; index <= count; index += 1) {
      var head = selectable
        ? '<label class="pick-enable-wrap"><input type="checkbox" class="pick-enable"> 第 ' +
          index +
          " 场</label>"
        : '<span class="pick-index">第 ' + index + " 场</span>";
      var choices = options
        .map(function (option, position) {
          return (
            '<label class="pick-option"><input type="radio" name="match-' +
            index +
            '" value="' +
            escapeHtml(option) +
            '"' +
            (position === 0 ? " checked" : "") +
            "><span>" +
            escapeHtml(option) +
            "</span></label>"
          );
        })
        .join("");
      rows +=
        '<div class="pick-row" data-row="' +
        index +
        '">' +
        head +
        '<div class="pick-options">' +
        choices +
        "</div></div>";
    }
    return (
      '<div class="pick-table">' +
      rows +
      "</div>" +
      (hint ? '<p class="hint">' + escapeHtml(hint) + "</p>" : "")
    );
  }

  function bqcTable(count) {
    var rows = "";
    for (var index = 1; index <= count; index += 1) {
      var options = ["3", "1", "0"]
        .map(function (value) {
          return '<option value="' + value + '">' + value + "</option>";
        })
        .join("");
      rows +=
        '<div class="pick-row" data-row="' +
        index +
        '"><span class="pick-index">第 ' +
        index +
        ' 场</span><div class="pick-options">' +
        '<label class="pick-select">半场 <select data-role="half">' +
        options +
        "</select></label>" +
        '<label class="pick-select">全场 <select data-role="full">' +
        options +
        "</select></label>" +
        "</div></div>";
    }
    return (
      '<div class="pick-table">' +
      rows +
      "</div>" +
      '<p class="hint">每场分别选择半场与全场结果（3 主胜 / 1 平 / 0 客胜）。</p>'
    );
  }

  function renderFields(code) {
    hideResult();
    hideError();

    if (code === "dlt") {
      fields.innerHTML =
        textField(
          "ticket",
          "号码",
          "01 02 03 04 05 + 01 02",
          "前区 5 个（1-35）+ 后区 2 个（1-12），可用空格、逗号或 + 分隔。"
        ) +
        '<label class="check-inline"><input type="checkbox" id="additional"> 追加投注（仅标记）</label>';
      return;
    }
    if (code === "ssq") {
      fields.innerHTML = textField(
        "ticket",
        "号码",
        "01 02 03 04 05 06 + 07",
        "红球 6 个（1-33）+ 蓝球 1 个（1-16）。"
      );
      return;
    }
    if (code === "pl3" || code === "fc3d") {
      fields.innerHTML =
        playTypeField([
          { value: "zhixuan", label: "直选" },
          { value: "zu3", label: "组选3" },
          { value: "zu6", label: "组选6" }
        ]) +
        textField("ticket", "号码", "3 4 6", "3 位数字（0-9）；组选3 需两位相同，组选6 需三位互不相同。");
      return;
    }
    if (code === "pl5") {
      fields.innerHTML = textField("ticket", "号码", "1 2 3 4 5", "5 位数字（0-9），逐位相同即中奖。");
      return;
    }
    if (code === "qxc") {
      fields.innerHTML = textField(
        "ticket",
        "号码",
        "1234567 或 1 2 3 4 5 6 + 7",
        "前区 6 位数字（0-9）+ 后区 1 位（0-14）。"
      );
      return;
    }
    if (code === "qlc") {
      fields.innerHTML = textField(
        "ticket",
        "基本号码",
        "01 02 03 04 05 06 07",
        "7 个不重复号码（1-30）；特别号由开奖结果给出。"
      );
      return;
    }
    if (code === "kl8") {
      fields.innerHTML = textField(
        "ticket",
        "投注号码",
        "01 05 10 12 18",
        "选择 1-10 个不重复号码（1-80），玩法按选号个数自动匹配。"
      );
      return;
    }
    if (code === "sfc14") {
      fields.innerHTML = pickTable(
        14,
        ["3", "1", "0"],
        false,
        "14 场逐场选择：3 主胜 / 1 平 / 0 客胜；全部命中为一等奖。"
      );
      return;
    }
    if (code === "rx9") {
      fields.innerHTML = pickTable(
        14,
        ["3", "1", "0"],
        true,
        "从 14 场中勾选 9 场，并为所选场次选择 3 / 1 / 0。"
      );
      return;
    }
    if (code === "jq4") {
      fields.innerHTML = pickTable(
        4,
        ["0", "1", "2", "3+"],
        false,
        "4 场逐场选择总进球档位（0 / 1 / 2 / 3+）。"
      );
      return;
    }
    if (code === "bqc6") {
      fields.innerHTML = bqcTable(6);
      return;
    }
    fields.innerHTML = '<div class="empty">该游戏暂不支持号码核对。</div>';
  }

  function collectPickRows(requireEnabled) {
    var rows = Array.prototype.slice.call(fields.querySelectorAll(".pick-row"));
    var picks = [];
    var enabledCount = 0;
    rows.forEach(function (row) {
      var index = Number(row.getAttribute("data-row"));
      var checkbox = row.querySelector(".pick-enable");
      if (requireEnabled) {
        if (!checkbox || !checkbox.checked) return;
        enabledCount += 1;
      }
      var radio = row.querySelector('input[type="radio"]:checked');
      if (!radio) throw new Error("请选择第 " + index + " 场的赛果");
      picks.push({ index: index, pick: radio.value });
    });
    if (requireEnabled && enabledCount !== 9) {
      throw new Error("任选9场请恰好勾选 9 场，当前已勾选 " + enabledCount + " 场");
    }
    return picks;
  }

  function collectBqcRows() {
    var rows = Array.prototype.slice.call(fields.querySelectorAll(".pick-row"));
    return rows.map(function (row) {
      var index = Number(row.getAttribute("data-row"));
      var half = row.querySelector('[data-role="half"]');
      var full = row.querySelector('[data-role="full"]');
      return { index: index, half: half.value, full: full.value };
    });
  }

  function buildRequest(code) {
    if (code === "dlt") {
      var dlt = parseTwoSide(valueOf("ticket"), 5, 2);
      if (dlt.front.length !== 5 || dlt.back.length !== 2) {
        throw new Error("前区需要 5 个号码、后区需要 2 个号码");
      }
      var additional = document.getElementById("additional");
      return {
        payload: { front: dlt.front, back: dlt.back },
        playType: additional && additional.checked ? "additional" : null
      };
    }
    if (code === "ssq") {
      var ssq = parseTwoSide(valueOf("ticket"), 6, 1);
      if (ssq.front.length !== 6 || ssq.back.length !== 1) {
        throw new Error("红球需要 6 个号码、蓝球需要 1 个号码");
      }
      return { payload: { red: ssq.front, blue: ssq.back }, playType: null };
    }
    if (code === "pl3" || code === "fc3d") {
      var digits3 = parseDigits(valueOf("ticket"), 3);
      if (digits3.length !== 3) throw new Error("请输入 3 位数字");
      var play = document.getElementById("play-type");
      return {
        payload: { digits: digits3 },
        playType: play ? play.value : "zhixuan"
      };
    }
    if (code === "pl5") {
      var digits5 = parseDigits(valueOf("ticket"), 5);
      if (digits5.length !== 5) throw new Error("请输入 5 位数字");
      return { payload: { digits: digits5 }, playType: null };
    }
    if (code === "qxc") {
      var qxc = parseQxc(valueOf("ticket"));
      if (qxc.front.length !== 6 || qxc.back === undefined || qxc.back === null) {
        throw new Error("请输入前区 6 位数字和后区 1 位数字");
      }
      return { payload: { front: qxc.front, back: qxc.back }, playType: null };
    }
    if (code === "qlc") {
      var basic = parseNumbers(valueOf("ticket"));
      if (basic.length !== 7) throw new Error("请输入 7 个基本号码");
      return { payload: { basic: basic }, playType: null };
    }
    if (code === "kl8") {
      var picks = parseNumbers(valueOf("ticket"));
      if (picks.length < 1 || picks.length > 10) {
        throw new Error("快乐8 请选择 1-10 个号码");
      }
      return { payload: { picks: picks }, playType: "select" + picks.length };
    }
    if (code === "sfc14") {
      return { payload: { picks: collectPickRows(false) }, playType: null };
    }
    if (code === "rx9") {
      return { payload: { picks: collectPickRows(true) }, playType: null };
    }
    if (code === "jq4") {
      return { payload: { picks: collectPickRows(false) }, playType: null };
    }
    if (code === "bqc6") {
      return { payload: { picks: collectBqcRows() }, playType: null };
    }
    throw new Error("该游戏暂不支持号码核对");
  }

  function formatDetailValue(key, value) {
    if (typeof value === "boolean") return value ? "是" : "否";
    if (key === "prize_amount") return value + " 元";
    if (Array.isArray(value)) {
      if (!value.length) return "无";
      if (value.every(function (item) {
        return item === null || typeof item !== "object";
      })) {
        return value.join("、");
      }
    }
    return null;
  }

  function detailHtml(detail) {
    if (!detail || typeof detail !== "object") return "";
    var simple = [];
    var complex = [];

    Object.keys(detail).forEach(function (key) {
      var value = detail[key];
      if (value === null || value === undefined || value === "") return;
      var text = formatDetailValue(key, value);
      if (text !== null) {
        simple.push(
          "<dt>" +
            escapeHtml(DETAIL_LABELS[key] || key) +
            "</dt><dd>" +
            escapeHtml(text) +
            "</dd>"
        );
      } else {
        complex.push(
          "<p class=\"detail-label\">" +
            escapeHtml(DETAIL_LABELS[key] || key) +
            '</p><pre class="payload">' +
            escapeHtml(JSON.stringify(value, null, 2)) +
            "</pre>"
        );
      }
    });

    var html = "";
    if (simple.length) html += '<dl class="kv-list">' + simple.join("") + "</dl>";
    if (complex.length) html += complex.join("");
    return html;
  }

  function renderResult(data) {
    var result = (data && data.result) || {};
    var draw = (data && data.draw) || {};
    var failed = result.ok === false;
    var hit = Boolean(result.hit);
    var tone = failed ? "notice-danger" : hit ? "notice-success" : "notice-info";
    var title = failed ? "无法核对" : hit ? "参考中奖" : "未中奖";

    var html =
      '<div class="notice ' +
      tone +
      '"><strong>' +
      title +
      '</strong><p style="margin:6px 0 0;">' +
      escapeHtml(result.message || "") +
      "</p></div>";
    html +=
      '<p class="meta-line">核对期号：第 ' +
      escapeHtml(draw.issue || "—") +
      " 期 · 开奖日期：" +
      escapeHtml(draw.date || "—") +
      "</p>";
    if (result.prize_level) {
      html +=
        '<p class="result-prize">参考奖级：<strong>' +
        escapeHtml(result.prize_level) +
        "</strong></p>";
    }
    html += detailHtml(result.detail);
    html +=
      '<p class="hint">核对结果仅供参考，奖金与兑奖以官方公告及实体票为准；本工具不代购、不出票、不自动兑奖。</p>';

    resultCard.hidden = false;
    resultRoot.innerHTML = html;
    resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError();
    hideResult();

    var request;
    try {
      request = buildRequest(currentCode);
    } catch (err) {
      showError(err.message);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "核对中…";
    api("/api/helper/check", {
      method: "POST",
      body: JSON.stringify({
        game_code: currentCode,
        play_type: request.playType || null,
        payload: request.payload || {}
      })
    })
      .then(renderResult)
      .catch(function (err) {
        showError(err && err.message ? err.message : "核对失败，请稍后重试");
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = "开始核对";
      });
  });

  resetBtn.addEventListener("click", function () {
    renderFields(currentCode);
  });

  gameSelect.addEventListener("change", function () {
    currentCode = gameSelect.value;
    try {
      window.history.replaceState(
        null,
        "",
        "?game=" + encodeURIComponent(currentCode)
      );
    } catch (err) {
      /* 忽略不支持 history 的环境 */
    }
    renderFields(currentCode);
  });

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
    api("/api/helper/games")
      .then(function (data) {
        games = [];
        var order = [
          "dlt",
          "pl3",
          "pl5",
          "qxc",
          "ssq",
          "fc3d",
          "qlc",
          "kl8",
          "sfc14",
          "rx9",
          "jq4",
          "bqc6"
        ];
        var byCode = {};
        ((data && data.groups) || []).forEach(function (group) {
          (group.games || []).forEach(function (game) {
            byCode[game.code] = game;
          });
        });
        order.forEach(function (code) {
          if (byCode[code] && byCode[code].support_level === "full") {
            games.push(byCode[code]);
          }
        });
        if (!games.length) {
          fields.innerHTML = '<div class="empty">暂无可核对游戏。</div>';
          submitBtn.disabled = true;
          return;
        }
        fillGames();
        submitBtn.disabled = false;
        hideError();
        var wanted = query("game");
        currentCode = games.some(function (game) {
          return game.code === wanted;
        })
          ? wanted
          : "dlt";
        gameSelect.value = currentCode;
        var issue = query("issue");
        if (issue) {
          issueHint.textContent =
            "链接指定期号：" + issue + "；当前核对以最新一期开奖为准。";
        }
        renderFields(currentCode);
      })
      .catch(function (err) {
        fields.innerHTML =
          '<div class="empty">游戏目录加载失败。' +
          '<div class="row-actions" style="justify-content:center;margin-top:12px;">' +
          '<button class="btn btn-primary btn-sm" type="button" id="games-retry">重新加载</button>' +
          "</div></div>";
        submitBtn.disabled = true;
        showError(err && err.message ? err.message : "加载游戏目录失败，请稍后重试");
        var retry = document.getElementById("games-retry");
        if (retry) retry.addEventListener("click", loadGames);
      });
  }

  loadGames();
})();
