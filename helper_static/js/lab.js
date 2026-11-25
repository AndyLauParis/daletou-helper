/* 历史数据实验室：读取统计接口并渲染图表（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("lab");

  var gameSelect = document.getElementById("lab-game");
  var windowSelect = document.getElementById("lab-window");
  var runBtn = document.getElementById("lab-run");
  var refreshBtn = document.getElementById("lab-refresh");
  var statusLine = document.getElementById("lab-status");
  var errorBox = document.getElementById("lab-error");
  var emptyBox = document.getElementById("lab-empty");
  var resultRoot = document.getElementById("lab-result");

  var summaryRoot = document.getElementById("lab-summary");
  var recentRoot = document.getElementById("recent-root");
  var frequencyRoot = document.getElementById("frequency-root");
  var shapeRoot = document.getElementById("shape-root");
  var testsMethod = document.getElementById("tests-method");
  var testsRoot = document.getElementById("tests-root");
  var testsNote = document.getElementById("tests-note");
  var backtestList = document.getElementById("backtest-list");
  var backtestChart = document.getElementById("backtest-chart");
  var backtestNote = document.getElementById("backtest-note");

  var budgetPeriods = document.getElementById("budget-periods");
  var budgetTickets = document.getElementById("budget-tickets");
  var budgetRun = document.getElementById("budget-run");
  var budgetError = document.getElementById("budget-error");
  var budgetUnsupported = document.getElementById("budget-unsupported");
  var budgetResult = document.getElementById("budget-result");
  var budgetSummary = document.getElementById("budget-summary");
  var budgetDistribution = document.getElementById("budget-distribution");
  var budgetPercentiles = document.getElementById("budget-percentiles");
  var budgetNote = document.getElementById("budget-note");

  var aiRun = document.getElementById("ai-run");
  var aiStatus = document.getElementById("ai-status");
  var aiLogin = document.getElementById("ai-login");
  var aiError = document.getElementById("ai-error");
  var aiOutput = document.getElementById("ai-output");
  var aiMeta = document.getElementById("ai-meta");
  var aiNotice = document.getElementById("ai-notice");

  var state = { games: [], analysis: null, loading: false, aiLoading: false };

  /* ------------------------------------------------------------------ */
  /* 工具函数                                                           */
  /* ------------------------------------------------------------------ */
  function show(element) {
    if (element) element.hidden = false;
  }

  function hide(element) {
    if (element) element.hidden = true;
  }

  function showError(box, message) {
    if (!box) return;
    box.textContent = message;
    box.hidden = false;
  }

  function hideError(box) {
    if (!box) return;
    box.textContent = "";
    box.hidden = true;
  }

  function pad2(value) {
    var num = Number(value);
    if (!isFinite(num)) return String(value);
    return num < 10 ? "0" + num : String(num);
  }

  function pct(value, digits) {
    var num = Number(value);
    if (!isFinite(num)) return "—";
    return (num * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }

  function fmt(value, digits) {
    var num = Number(value);
    if (!isFinite(num)) return "—";
    return num.toLocaleString("zh-CN", {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits === undefined ? 2 : digits
    });
  }

  function money(value) {
    var num = Number(value);
    if (!isFinite(num)) return "—";
    var text = Math.abs(num).toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
    return (num < 0 ? "−¥" : "¥") + text;
  }

  function fmtSigned(value) {
    var num = Number(value);
    if (!isFinite(num)) return "—";
    var text = fmt(Math.abs(num), 3);
    if (num > 0) return "+" + text;
    if (num < 0) return "−" + text;
    return "0";
  }

  function fmtP(value) {
    var num = Number(value);
    if (!isFinite(num)) return "—";
    if (num < 0.001) return "<0.001";
    return num.toFixed(3);
  }

  function clampInt(value, low, high) {
    var num = parseInt(value, 10);
    if (!isFinite(num)) num = low;
    return Math.min(high, Math.max(low, num));
  }

  function statCard(label, value, note, valueClass) {
    return (
      '<div class="stat"><p class="stat-label">' +
      escapeHtml(label) +
      '</p><p class="stat-value' +
      (valueClass ? " " + valueClass : "") +
      '">' +
      escapeHtml(value) +
      "</p>" +
      (note ? '<p class="hint">' + escapeHtml(note) + "</p>" : "") +
      "</div>"
    );
  }

  function histRows(rows) {
    var counts = rows.map(function (row) {
      return Number(row.count) || 0;
    });
    var max = Math.max.apply(null, counts.concat([1]));
    return rows
      .map(function (row) {
        var count = Number(row.count) || 0;
        var width = Math.max(1, Math.round((count / max) * 100));
        return (
          '<div class="lab-hist-row"><span class="lab-hist-label">' +
          escapeHtml(row.label) +
          '</span><span class="lab-hist-track"><span class="lab-hist-fill" style="width:' +
          width +
          '%"></span></span><span class="lab-hist-count">' +
          escapeHtml(String(count)) +
          "</span></div>"
        );
      })
      .join("");
  }

  function histChart(title, rows, unit) {
    return (
      '<div class="lab-chart"><h3 class="lab-chart-title">' +
      escapeHtml(title) +
      '</h3><div class="lab-hist">' +
      histRows(rows) +
      "</div>" +
      (unit ? '<p class="hint">' + escapeHtml(unit) + "</p>" : "") +
      "</div>"
    );
  }

  function isDigitGame(code) {
    return code === "pl3" || code === "fc3d" || code === "pl5" || code === "qxc";
  }

  function renderGroupNumbers(code, group) {
    var numbers = group.numbers || [];
    if (isDigitGame(code)) {
      return (
        '<span class="digits-line">' +
        numbers
          .map(function (value) {
            return '<span class="digit">' + escapeHtml(pad2(value)) + "</span>";
          })
          .join("") +
        "</span>"
      );
    }
    var cls = "ball-front";
    if (group.key === "back" || group.key === "blue") cls = "ball-back";
    if (group.key === "special") cls = "ball-special";
    return (
      '<span class="balls">' +
      numbers
        .map(function (value) {
          return (
            '<span class="ball ' +
            cls +
            '">' +
            escapeHtml(pad2(value)) +
            "</span>"
          );
        })
        .join("") +
      "</span>"
    );
  }

  /* ------------------------------------------------------------------ */
  /* 游戏列表与分析                                                     */
  /* ------------------------------------------------------------------ */
  async function loadGames() {
    try {
      var data = await api("/api/helper/lab/games", { redirectOn401: false });
      state.games = (data && data.games) || [];
      gameSelect.innerHTML = "";
      if (!state.games.length) {
        gameSelect.innerHTML = '<option value="">暂无可分析游戏</option>';
        emptyBox.textContent = "暂无可分析的游戏数据，请稍后再试。";
        statusLine.textContent = "未读取到可分析的游戏。";
        return;
      }

      state.games.forEach(function (game) {
        var option = document.createElement("option");
        option.value = game.code;
        option.textContent = game.name + "（" + game.draw_count + " 期）";
        if (game.draw_count < 10) option.disabled = true;
        gameSelect.appendChild(option);
      });

      var preferred =
        state.games.filter(function (game) {
          return game.code === "dlt" && game.draw_count >= 10;
        })[0] ||
        state.games.filter(function (game) {
          return game.draw_count >= 10;
        })[0];

      if (preferred) {
        gameSelect.value = preferred.code;
        runAnalysis();
      } else {
        statusLine.textContent = "暂无足够样本的游戏（至少需要 10 期）。";
        emptyBox.textContent = "暂无足够的历史样本，可先到“开奖核对”页更新开奖数据。";
      }
    } catch (err) {
      showError(errorBox, err.message || "读取游戏列表失败");
      statusLine.textContent = "读取游戏列表失败。";
    }
  }

  async function runAnalysis() {
    var code = gameSelect.value;
    if (!code || state.loading) return;

    state.loading = true;
    state.analysis = null;
    resetAi();
    runBtn.disabled = true;
    refreshBtn.disabled = true;
    hideError(errorBox);
    hide(resultRoot);
    show(emptyBox);
    emptyBox.textContent = "正在计算历史统计，请稍候…";
    statusLine.textContent = "正在计算…";

    try {
      var windowValue = clampInt(windowSelect.value, 10, 200);
      var data = await api(
        "/api/helper/lab/analysis?game=" +
          encodeURIComponent(code) +
          "&window=" +
          windowValue,
        { redirectOn401: false }
      );
      state.analysis = data;
      renderAnalysis(data);
      resetAi();
      hide(emptyBox);
      show(resultRoot);
      statusLine.textContent =
        "已分析 " +
        data.game.name +
        " 最近 " +
        data.window_used +
        " 期（" +
        data.date_range.from +
        " 至 " +
        data.date_range.to +
        "），本地缓存共 " +
        data.available_draws +
        " 期。";

      if (data.game.budget_supported) {
        hide(budgetUnsupported);
        runBudget();
      } else {
        hide(budgetResult);
        show(budgetUnsupported);
      }
    } catch (err) {
      state.analysis = null;
      emptyBox.textContent =
        err.message || "分析失败，请稍后重试。";
      statusLine.textContent = "分析未完成。";
    } finally {
      state.loading = false;
      runBtn.disabled = false;
      refreshBtn.disabled = false;
    }
  }

  function renderAnalysis(data) {
    var code = data.game.code;

    summaryRoot.innerHTML =
      statCard("样本期数", data.window_used + " 期", "请求 " + data.window_requested + " 期") +
      statCard(
        "时间范围",
        data.date_range.from + " 至 " + data.date_range.to,
        "按开奖日期排序",
        "tiny"
      ) +
      statCard("最新期号", data.latest_issue || "—", "数据以官方发布为准") +
      statCard("本地缓存", data.available_draws + " 期", "不含本次网络更新");

    recentRoot.innerHTML = data.recent
      .map(function (item) {
        var groups = item.groups
          .map(function (group) {
            return (
              '<div class="number-group"><span class="number-label">' +
              escapeHtml(group.label) +
              "</span>" +
              renderGroupNumbers(code, group) +
              "</div>"
            );
          })
          .join("");
        var repeat =
          item.repeat === null || item.repeat === undefined ? "—" : item.repeat;
        return (
          '<article class="draw-item"><div class="draw-head">' +
          '<div><span class="draw-issue">第 ' +
          escapeHtml(item.issue) +
          ' 期</span><span class="draw-date">' +
          escapeHtml(item.date) +
          "</span></div>" +
          '<div class="badges"><span class="badge badge-muted">和值 ' +
          escapeHtml(String(item.sum)) +
          '</span><span class="badge badge-muted">跨度 ' +
          escapeHtml(String(item.span)) +
          '</span><span class="badge badge-muted">奇数 ' +
          escapeHtml(String(item.odd)) +
          '</span><span class="badge badge-muted">重号 ' +
          escapeHtml(String(repeat)) +
          "</span></div></div>" +
          groups +
          "</article>"
        );
      })
      .join("");

    renderFrequency(data);
    renderShape(data);
    renderTests(data.randomness);
    renderBacktest(data);
  }

  function renderFrequency(data) {
    frequencyRoot.innerHTML = data.frequency
      .map(function (group) {
        var counts = group.numbers.map(function (row) {
          return Number(row.count) || 0;
        });
        var max = Math.max.apply(null, counts.concat([1]));
        var cells = group.numbers
          .map(function (row) {
            var count = Number(row.count) || 0;
            var width = Math.max(2, Math.round((count / max) * 100));
            return (
              '<div class="freq-cell" title="号码 ' +
              escapeHtml(pad2(row.number)) +
              "：出现 " +
              escapeHtml(String(count)) +
              " 次（" +
              escapeHtml(pct(row.rate, 2)) +
              "），当前遗漏 " +
              escapeHtml(String(row.current_omission)) +
              " 期，最长遗漏 " +
              escapeHtml(String(row.max_omission)) +
              ' 期"><div class="freq-top"><span class="freq-num">' +
              escapeHtml(pad2(row.number)) +
              '</span><span class="freq-omit">遗漏 ' +
              escapeHtml(String(row.current_omission)) +
              '</span></div><span class="freq-track"><span class="freq-fill" style="width:' +
              width +
              '%"></span></span><span class="freq-meta">' +
              escapeHtml(String(count)) +
              " 次</span></div>"
            );
          })
          .join("");
        return (
          '<div class="lab-group"><div class="lab-group-head"><h3 class="lab-group-title">' +
          escapeHtml(group.label) +
          '</h3><span class="badge badge-muted">' +
          escapeHtml(String(group.pool)) +
          " 个号码 · 期望 " +
          escapeHtml(pct(group.pick / group.pool, 2)) +
          "</span></div>" +
          '<div class="freq-grid">' +
          cells +
          "</div></div>"
        );
      })
      .join("");
  }

  function renderShape(data) {
    var shape = data.shape;
    var html = "";

    html +=
      '<div class="stat-grid">' +
      statCard(
        "和值均值",
        fmt(shape.sum.mean),
        "理论 " + fmt(shape.sum.theoretical_mean)
      ) +
      statCard(
        "和值标准差",
        fmt(shape.sum.stdev),
        "最小 " + shape.sum.min + " · 最大 " + shape.sum.max
      ) +
      statCard(
        "奇数个数均值",
        fmt(shape.odd.mean),
        "理论 " + fmt(shape.odd.theoretical_mean)
      ) +
      statCard(
        "相邻期重号均值",
        fmt(shape.repeat.mean),
        "理论 " + fmt(shape.repeat.theoretical_mean)
      ) +
      "</div>";

    html += '<div class="lab-chart-grid">';
    html += histChart("和值分布", shape.sum.histogram);
    html += histChart("跨度分布", shape.span.histogram);
    html += histChart("奇数个数分布", shape.odd.histogram);
    if (shape.consecutive) {
      html += histChart("连号对数分布", shape.consecutive.histogram);
    }
    if (shape.repeat.histogram && shape.repeat.histogram.length) {
      html += histChart("相邻期重号分布", shape.repeat.histogram);
    }
    html += "</div>";

    html += '<div class="lab-chart"><h3 class="lab-chart-title">三区分布</h3>';
    shape.zones.forEach(function (zone) {
      var width = Math.max(2, Math.round(Math.min(1, zone.share) * 100));
      html +=
        '<div class="lab-zone-row"><span class="lab-hist-label">' +
        escapeHtml(zone.label) +
        '</span><span class="lab-hist-track"><span class="lab-hist-fill" style="width:' +
        width +
        '%"></span></span><span class="lab-hist-count">' +
        escapeHtml(fmt(zone.avg)) +
        " / 期</span></div>";
    });
    html +=
      '<p class="hint">每期平均落入各区的号码个数；完全随机时每区期望 ' +
      escapeHtml(fmt(shape.zones[0] ? shape.zones[0].expected : 0)) +
      " 个。</p></div>";

    shapeRoot.innerHTML = html;
  }

  function renderTests(randomness) {
    testsMethod.textContent =
      randomness.method + " 共 " + randomness.trials + " 次模拟。";
    testsRoot.innerHTML = randomness.tests
      .map(function (test) {
        var warn = Number(test.p_value) < 0.05;
        return (
          '<article class="lab-test' +
          (warn ? " lab-test-warn" : "") +
          '"><div class="lab-test-head"><h3 class="lab-test-title">' +
          escapeHtml(test.label) +
          '</h3><span class="badge ' +
          (warn ? "badge-warn" : "badge-ok") +
          '">p = ' +
          escapeHtml(fmtP(test.p_value)) +
          "</span></div>" +
          '<div class="lab-test-values"><span>观测 ' +
          escapeHtml(fmt(test.observed, 4)) +
          "</span><span>随机均值 " +
          escapeHtml(fmt(test.null_mean, 4)) +
          "</span><span>90% 区间 " +
          escapeHtml(fmt(test.null_p05, 4)) +
          " – " +
          escapeHtml(fmt(test.null_p95, 4)) +
          "</span></div><p>" +
          escapeHtml(test.verdict) +
          '</p><p class="small">' +
          escapeHtml(test.detail) +
          "</p></article>"
        );
      })
      .join("");
    testsNote.textContent = randomness.note;
  }

  function renderBacktest(data) {
    var backtest = data.backtest;
    backtestList.innerHTML = backtest.strategies
      .map(function (strategy) {
        return (
          '<article class="lab-strategy"><div class="lab-strategy-head"><div><h3 class="lab-strategy-title">' +
          escapeHtml(strategy.label) +
          '</h3><p class="lab-strategy-detail">' +
          escapeHtml(strategy.detail) +
          '</p></div><span class="badge badge-muted">' +
          escapeHtml(String(strategy.tickets)) +
          ' 注</span></div><div class="lab-strategy-metrics">' +
          '<div class="lab-metric"><span>平均命中</span><strong>' +
          escapeHtml(fmt(strategy.avg_hits, 3)) +
          '</strong></div><div class="lab-metric"><span>理论期望</span><strong>' +
          escapeHtml(fmt(backtest.expected_hits, 3)) +
          '</strong></div><div class="lab-metric"><span>差异</span><strong>' +
          escapeHtml(fmtSigned(strategy.diff_from_expected)) +
          '</strong></div><div class="lab-metric"><span>最高命中</span><strong>' +
          escapeHtml(String(strategy.max_hits)) +
          "</strong></div></div></article>"
        );
      })
      .join("");

    var rows = backtest.strategies
      .map(function (strategy) {
        return {
          label: strategy.label,
          count: Number(strategy.avg_hits) || 0
        };
      })
      .concat([
        { label: "理论期望", count: Number(backtest.expected_hits) || 0 }
      ]);
    backtestChart.innerHTML =
      '<h3 class="lab-chart-title">平均命中个数对比</h3>' +
      '<div class="lab-hist">' +
      histRows(rows) +
      "</div>";
    backtestNote.textContent = backtest.note;
  }

  /* ------------------------------------------------------------------ */
  /* AI 辅助解读                                                        */
  /* ------------------------------------------------------------------ */
  function formatStamp(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
  }

  function resetAi() {
    state.aiLoading = false;
    hideError(aiError);
    aiOutput.textContent = "";
    hide(aiOutput);
    hide(aiMeta);
    hide(aiNotice);
    aiRun.textContent = "生成解读";
    aiRun.disabled = !state.analysis;
    var loggedIn = !!(window.isLoggedIn && window.isLoggedIn());
    aiLogin.hidden = loggedIn;
    aiStatus.textContent = loggedIn
      ? "基于当前分析生成通俗解读；每次生成会消耗模型额度，按账号限流。"
      : "需要登录后使用；生成会消耗模型额度，按账号限流。";
  }

  async function runAi() {
    if (!state.analysis || state.aiLoading) return;
    state.aiLoading = true;
    aiRun.disabled = true;
    aiRun.textContent = "生成中…";
    hideError(aiError);
    hide(aiMeta);
    hide(aiNotice);
    aiOutput.textContent = "正在请求大模型，请稍候…";
    show(aiOutput);
    aiStatus.textContent = "正在请求大模型，通常需要几秒…";

    try {
      var data = await api("/api/helper/lab/interpret", {
        method: "POST",
        body: JSON.stringify({
          game: state.analysis.game.code,
          window: clampInt(windowSelect.value, 10, 200),
          periods: clampInt(budgetPeriods.value, 1, 520),
          tickets: clampInt(budgetTickets.value, 1, 20),
          include_budget: !!state.analysis.game.budget_supported
        }),
        redirectOn401: false
      });
      var text = (data && data.text) || "";
      if (!text) throw new Error("大模型返回了空内容，请稍后再试");
      aiOutput.textContent = text;
      show(aiOutput);
      aiRun.textContent = "重新生成";
      aiStatus.textContent = "解读完成。AI 内容可能有误，请以本页统计与官方开奖为准。";
      aiMeta.textContent =
        "由 " +
        ((data && data.provider) || "大模型") +
        " · " +
        ((data && data.model) || "未知模型") +
        " 生成" +
        (data && data.cached ? "（缓存结果）" : "") +
        " · " +
        formatStamp(data && data.generated_at);
      show(aiMeta);
      aiNotice.textContent =
        (data && data.notice) ||
        "AI 生成内容可能有误，不预测开奖、不推荐号码，也不构成投注建议。";
      show(aiNotice);
      aiLogin.hidden = true;
    } catch (err) {
      hide(aiOutput);
      aiOutput.textContent = "";
      showError(aiError, (err && err.message) || "生成失败，请稍后重试");
      aiStatus.textContent = "生成失败，可稍后重试。";
      aiRun.textContent = "生成解读";
      if (((err && err.message) || "").indexOf("登录") !== -1) {
        show(aiLogin);
      }
    } finally {
      state.aiLoading = false;
      aiRun.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /* 预算模拟                                                           */
  /* ------------------------------------------------------------------ */
  async function runBudget() {
    if (!state.analysis || !state.analysis.game.budget_supported) {
      show(budgetUnsupported);
      return;
    }
    hideError(budgetError);
    budgetRun.disabled = true;
    try {
      var periods = clampInt(budgetPeriods.value, 1, 520);
      var tickets = clampInt(budgetTickets.value, 1, 20);
      budgetPeriods.value = periods;
      budgetTickets.value = tickets;
      var data = await api(
        "/api/helper/lab/budget?game=" +
          encodeURIComponent(state.analysis.game.code) +
          "&periods=" +
          periods +
          "&tickets=" +
          tickets,
        { redirectOn401: false }
      );
      renderBudget(data);
      show(budgetResult);
    } catch (err) {
      showError(budgetError, err.message || "预算模拟失败");
    } finally {
      budgetRun.disabled = false;
    }
  }

  function renderBudget(data) {
    budgetSummary.innerHTML =
      statCard("累计投入", money(data.spend), data.periods + " 期 × " + data.tickets_per_period + " 注") +
      statCard("平均返奖", money(data.avg_return), "仅含固定奖级") +
      statCard("平均净支出", money(data.avg_net), "返奖减投入") +
      statCard("亏损概率", pct(data.p_loss, 1), "模拟 " + data.trials + " 次");

    var maxShare = Math.max.apply(
      null,
      data.distribution.map(function (row) {
        return Number(row.share) || 0;
      }).concat([0.0001])
    );
    budgetDistribution.innerHTML = data.distribution
      .map(function (row) {
        var share = Number(row.share) || 0;
        var width = Math.max(1, Math.round((share / maxShare) * 100));
        return (
          '<div class="lab-hist-row"><span class="lab-hist-label">' +
          escapeHtml(row.label) +
          '</span><span class="lab-hist-track"><span class="lab-hist-fill" style="width:' +
          width +
          '%"></span></span><span class="lab-hist-count">' +
          escapeHtml(pct(share, 1)) +
          "</span></div>"
        );
      })
      .join("");

    var percentiles = data.net_percentiles;
    budgetPercentiles.innerHTML = [
      ["5%", percentiles.p05],
      ["25%", percentiles.p25],
      ["50%", percentiles.p50],
      ["75%", percentiles.p75],
      ["95%", percentiles.p95]
    ]
      .map(function (entry) {
        return (
          '<div class="lab-percentile"><span>' +
          escapeHtml(entry[0]) +
          "</span><strong>" +
          escapeHtml(money(entry[1])) +
          "</strong></div>"
        );
      })
      .join("");

    budgetNote.textContent =
      data.note +
      " 单注命中任一固定奖的概率约为 " +
      pct(data.per_ticket_any_prize, 3) +
      "。";
  }

  /* ------------------------------------------------------------------ */
  /* 事件绑定                                                           */
  /* ------------------------------------------------------------------ */
  runBtn.addEventListener("click", runAnalysis);
  gameSelect.addEventListener("change", function () {
    windowSelect.value = "100";
    runAnalysis();
  });
  refreshBtn.addEventListener("click", async function () {
    var code = gameSelect.value;
    if (!code) return;
    refreshBtn.disabled = true;
    hideError(errorBox);
    statusLine.textContent = "正在请求官方数据源，可能需要几秒钟…";
    try {
      var data = await api(
        "/api/helper/games/" + encodeURIComponent(code) + "/refresh",
        { method: "POST" }
      );
      if (data && data.ok === false) {
        statusLine.textContent = data.message || "本次更新未成功。";
      } else {
        statusLine.textContent = "数据已更新，正在重新分析…";
      }
      await runAnalysis();
    } catch (err) {
      showError(errorBox, err.message || "更新开奖数据失败");
      statusLine.textContent = "更新开奖数据失败。";
    } finally {
      refreshBtn.disabled = false;
    }
  });
  budgetRun.addEventListener("click", runBudget);
  aiRun.addEventListener("click", runAi);

  loadGames();
})();
