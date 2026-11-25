/* 娱乐选号工具：按组合规则生成号码，不预测开奖。 */
(function () {
  "use strict";

  mountShell("picker");

  var gameSelect = document.getElementById("game");
  var methodSelect = document.getElementById("method");
  var ticketsSelect = document.getElementById("tickets");
  var generateBtn = document.getElementById("generate");
  var methodLabel = document.getElementById("method-label");
  var methodDesc = document.getElementById("method-desc");
  var statusLine = document.getElementById("status");
  var errorBox = document.getElementById("error");

  var resultRoot = document.getElementById("result");
  var resultGame = document.getElementById("result-game");
  var resultMethodLabel = document.getElementById("result-method-label");
  var resultMethodDesc = document.getElementById("result-method-desc");
  var resultBasis = document.getElementById("result-basis");
  var resultConstraints = document.getElementById("result-constraints");
  var ticketList = document.getElementById("ticket-list");
  var againBtn = document.getElementById("again");
  var changeBtn = document.getElementById("change");

  var state = { options: null, loading: false };

  function show(element) {
    element.hidden = false;
  }

  function hide(element) {
    element.hidden = true;
  }

  function showError(message) {
    errorBox.textContent = message;
    show(errorBox);
  }

  function clearError() {
    errorBox.textContent = "";
    hide(errorBox);
  }

  function currentGame() {
    if (!state.options) return null;
    return state.options.games.find(function (game) {
      return game.code === gameSelect.value;
    }) || null;
  }

  function availableMethods() {
    var game = currentGame();
    if (!state.options) return [];
    return state.options.methods.filter(function (method) {
      return method.scope !== "lottery" || !(game && game.digit_mode);
    });
  }

  function currentMethod() {
    return availableMethods().find(function (method) {
      return method.key === methodSelect.value;
    }) || null;
  }

  function updateMethodInfo() {
    var method = currentMethod();
    if (!method) return;
    methodLabel.textContent = method.label;
    methodDesc.textContent = method.description;
  }

  function fillMethods() {
    var previous = methodSelect.value;
    var methods = availableMethods();
    methodSelect.innerHTML = methods
      .map(function (method) {
        return (
          '<option value="' +
          escapeHtml(method.key) +
          '">' +
          escapeHtml(method.label) +
          "</option>"
        );
      })
      .join("");
    var stillAvailable = methods.some(function (method) {
      return method.key === previous;
    });
    methodSelect.value = stillAvailable ? previous : "random";
    updateMethodInfo();
  }

  function ticketHtml(ticket, index, digitMode) {
    var groups = ticket
      .map(function (group) {
        var numbers = group.numbers
          .map(function (item) {
            var className = digitMode ? "digit" : "ball";
            return (
              '<span class="' +
              className +
              '">' +
              escapeHtml(item.display) +
              "</span>"
            );
          })
          .join("");
        return (
          '<div class="picker-group">' +
          '<span class="picker-group-label">' +
          escapeHtml(group.label) +
          "</span>" +
          '<span class="picker-number-row">' +
          numbers +
          "</span>" +
          "</div>"
        );
      })
      .join("");
    return (
      '<article class="picker-ticket">' +
      '<div class="picker-ticket-head">' +
      "<span>第 " +
      (index + 1) +
      " 注</span>" +
      '<span class="muted small">等概率组合</span>' +
      "</div>" +
      '<div class="picker-ticket-groups">' +
      groups +
      "</div>" +
      "</article>"
    );
  }

  function renderResult(data) {
    resultGame.textContent =
      data.game.name + " · " + (data.game.format_summary || "");
    resultMethodLabel.textContent = data.method.label + " · 号码组合";
    resultMethodDesc.textContent = data.method.description;

    var info = data.data || {};
    if (info.window) {
      resultBasis.textContent =
        "基于最近 " +
        info.window +
        " 期历史缓存（最新期号 " +
        (info.latest_issue || "—") +
        "）计算权重；历史样本只用于组合，不预测开奖。";
    } else {
      resultBasis.textContent = "历史样本不足，本次按纯随机组合生成。";
    }

    var notes = data.constraints || [];
    if (notes.length) {
      resultConstraints.textContent = notes.join("；");
      show(resultConstraints);
    } else {
      resultConstraints.textContent = "";
      hide(resultConstraints);
    }

    ticketList.innerHTML = (data.tickets || [])
      .map(function (ticket, index) {
        return ticketHtml(ticket, index, !!data.game.digit_mode);
      })
      .join("");
    show(resultRoot);
    statusLine.textContent =
      "已生成 " +
      (data.tickets || []).length +
      " 注娱乐组合，不构成购彩建议。";
  }

  async function generate() {
    if (state.loading || !state.options) return;
    var game = currentGame();
    var method = currentMethod();
    if (!game || !method) return;

    state.loading = true;
    clearError();
    generateBtn.disabled = true;
    generateBtn.textContent = "生成中…";
    statusLine.textContent = "正在按所选规则生成号码…";

    try {
      var data = await api("/api/helper/picker/generate", {
        method: "POST",
        body: JSON.stringify({
          game: game.code,
          method: method.key,
          tickets: parseInt(ticketsSelect.value, 10) || 1
        })
      });
      renderResult(data);
    } catch (err) {
      hide(resultRoot);
      showError((err && err.message) || "生成失败，请稍后重试");
      statusLine.textContent = "生成失败，可重新选择后再试。";
    } finally {
      state.loading = false;
      generateBtn.disabled = false;
      generateBtn.textContent = "生成号码";
    }
  }

  async function loadOptions() {
    try {
      var data = await api("/api/helper/picker/options");
      state.options = data;

      var preferred = data.games.some(function (game) {
        return game.code === "dlt";
      })
        ? "dlt"
        : data.games[0] && data.games[0].code;
      gameSelect.innerHTML = data.games
        .map(function (game) {
          return (
            '<option value="' +
            escapeHtml(game.code) +
            '">' +
            escapeHtml(game.name) +
            "</option>"
          );
        })
        .join("");
      if (preferred) gameSelect.value = preferred;
      fillMethods();
      await generate();
    } catch (err) {
      showError((err && err.message) || "加载选号选项失败，请刷新重试");
      statusLine.textContent = "暂时无法加载选号选项。";
    }
  }

  gameSelect.addEventListener("change", function () {
    fillMethods();
    generate();
  });

  methodSelect.addEventListener("change", function () {
    updateMethodInfo();
    generate();
  });

  ticketsSelect.addEventListener("change", generate);
  generateBtn.addEventListener("click", generate);
  againBtn.addEventListener("click", generate);
  changeBtn.addEventListener("click", function () {
    methodSelect.focus();
    document.getElementById("controls").scrollIntoView({ behavior: "smooth", block: "start" });
  });

  loadOptions();
})();
