/* ==========================================================================
   大乐透三大模型 · 数据实验室
   原生 JS，无构建步骤。图表使用本地 ECharts。
   ========================================================================== */
(function () {
  "use strict";

  var SECTIONS = ["overview", "model1", "model2", "model3", "history", "conclusion"];
  var ECHARTS = window.echarts;

  var C = {
    ink: "#0B1220",
    cream: "#F2EAD9",
    creamDim: "#D8CFBE",
    muted: "#93A1B5",
    muted2: "#6F7D91",
    red: "#E4572E",
    amber: "#E9A23B",
    teal: "#39B5A5",
    steel: "#6C93C0",
    grid: "rgba(242,234,217,0.08)",
    line: "rgba(242,234,217,0.18)"
  };

  var state = {
    active: "overview",
    overview: null,
    model1: null,
    model2: null,
    model3: null,
    history: null,
    rules: null,
    rulesKey: "",
    computed: { model1: false, model2: false, model3: false, history: false },
    freqView: "front",
    omitView: "front"
  };

  var charts = new Map();
  var seq = { model1: 0, model2: 0, model3: 0, history: 0 };

  /* ---------------------------------------------------------------- DOM */

  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    var el = $(id);
    if (el) el.textContent = text == null ? "—" : String(text);
  }

  function setNote(valueId, text) {
    var el = $(valueId);
    if (!el || !el.parentElement) return;
    var note = el.parentElement.querySelector(".metric-note");
    if (note) note.textContent = text;
  }

  function clearNode(el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var self = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(self, args);
      }, wait == null ? 300 : wait);
    };
  }

  /* ------------------------------------------------------------ numbers */

  function toNum(value) {
    if (typeof value === "number") return isFinite(value) ? value : null;
    if (typeof value === "string" && value.trim() !== "") {
      var n = Number(value);
      return isFinite(n) ? n : null;
    }
    return null;
  }

  function trimFixed(value, digits) {
    var n = toNum(value);
    if (n === null) return "—";
    var text = n.toFixed(digits == null ? 2 : digits);
    if (text.indexOf(".") >= 0) text = text.replace(/0+$/, "").replace(/\.$/, "");
    if (text === "-0") text = "0";
    return text;
  }

  function fmtInt(value) {
    var n = toNum(value);
    if (n === null) return "—";
    return Math.round(n).toLocaleString("zh-CN");
  }

  function fmtMoney(value) {
    var n = toNum(value);
    if (n === null) return "—";
    var abs = Math.abs(n);
    if (abs >= 1e8) return trimFixed(n / 1e8, 2) + " 亿";
    if (abs >= 1e4) return trimFixed(n / 1e4, 2) + " 万";
    return trimFixed(n, 2) + " 元";
  }

  function fmtMoneySigned(value) {
    var n = toNum(value);
    if (n === null) return "—";
    var abs = Math.abs(n);
    var body;
    if (abs >= 1e8) body = trimFixed(abs / 1e8, 2) + " 亿";
    else if (abs >= 1e4) body = trimFixed(abs / 1e4, 2) + " 万";
    else body = trimFixed(abs, 2) + " 元";
    return (n < 0 ? "−" : "+") + body;
  }

  var SUP = {
    "-": "⁻",
    "+": "⁺",
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹"
  };

  function superscript(exp) {
    return String(exp)
      .split("")
      .map(function (ch) {
        return SUP[ch] || ch;
      })
      .join("");
  }

  function fmtSci(value, digits) {
    var n = toNum(value);
    if (n === null) return "—";
    if (n === 0) return "0";
    var exp = Math.floor(Math.log10(Math.abs(n)));
    var mant = n / Math.pow(10, exp);
    if (Math.abs(mant) >= 10) {
      mant /= 10;
      exp += 1;
    } else if (Math.abs(mant) < 1) {
      mant *= 10;
      exp -= 1;
    }
    return trimFixed(mant, digits == null ? 3 : digits) + "×10" + superscript(exp);
  }

  function fmtPct(value, digits) {
    var n = toNum(value);
    if (n === null) return "—";
    if (n === 0) return "0%";
    if (Math.abs(n) < 1e-4) return fmtSci(n * 100, 3) + "%";
    return trimFixed(n * 100, digits == null ? 2 : digits) + "%";
  }

  function fmtRatio(value) {
    var n = toNum(value);
    if (n === null) return "—";
    if (Math.abs(n) < 1e-4 && n !== 0) return fmtSci(n, 3);
    return trimFixed(n, 4);
  }

  function fmtOneIn(prob) {
    var p = toNum(prob);
    if (p === null || p <= 0) return "—";
    if (p >= 1) return "1 / 1";
    return "1 / " + fmtInt(1 / p);
  }

  function fmtDay(secondsValue) {
    var seconds = toNum(secondsValue);
    if (seconds === null) return "—";
    if (seconds < 3600) return trimFixed(seconds / 60, 1) + " 分钟";
    if (seconds < 86400) return trimFixed(seconds / 3600, 1) + " 小时";
    if (seconds < 86400 * 3650) return trimFixed(seconds / 86400, 1) + " 天";
    return trimFixed(seconds / (86400 * 365), 1) + " 年";
  }

  function atLeastOnce(p, n) {
    var prob = toNum(p);
    var count = toNum(n);
    if (prob === null || count === null) return null;
    if (count <= 0 || prob <= 0) return 0;
    if (prob >= 1) return 1;
    return -Math.expm1(count * Math.log1p(-prob));
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function pick(obj, keys, fallback) {
    if (!obj || typeof obj !== "object") return fallback;
    for (var i = 0; i < keys.length; i += 1) {
      if (obj[keys[i]] !== undefined && obj[keys[i]] !== null) return obj[keys[i]];
    }
    return fallback;
  }

  function pickNum(obj, keys) {
    return toNum(pick(obj, keys, null));
  }

  /* ---------------------------------------------------------------- API */

  async function request(url, options) {
    var opts = options || {};
    var timeout = opts.timeout || 20000;
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, timeout);
    try {
      var resp = await fetch(url, {
        method: opts.method || "GET",
        headers: opts.headers,
        body: opts.body,
        signal: controller.signal,
        cache: "no-store"
      });
      if (resp.status === 503) {
        var loading = new Error("模型模块加载中");
        loading.status = 503;
        throw loading;
      }
      if (!resp.ok) {
        var message = "请求失败（HTTP " + resp.status + "）";
        try {
          var payload = await resp.json();
          if (payload && payload.detail) message = String(payload.detail);
        } catch (ignore) {
          /* 非 JSON 错误体 */
        }
        var err = new Error(message);
        err.status = resp.status;
        throw err;
      }
      return await resp.json();
    } catch (error) {
      if (error && error.name === "AbortError") {
        var timeoutError = new Error("请求超时，请检查后端是否启动");
        timeoutError.timeout = true;
        throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function getJSON(url, timeout) {
    return request(url, { method: "GET", timeout: timeout });
  }

  function postJSON(url, body, timeout) {
    return request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      timeout: timeout || 20000
    });
  }

  function errorMessage(error) {
    if (!error) return "未知错误";
    if (error.status === 503) return "模型模块加载中，后端正在准备计算模块。";
    return error.message || "请求失败";
  }

  /* ------------------------------------------------------------- alerts */

  function setAlert(key, kind, message, retry) {
    var el = document.querySelector('[data-alert="' + key + '"]');
    if (!el) return;
    clearNode(el);
    if (!message) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.dataset.kind = kind || "error";
    var title = document.createElement("span");
    title.className = "alert-title";
    title.textContent = kind === "loading" ? "加载中" : "请求失败";
    var body = document.createElement("span");
    body.className = "alert-message";
    body.textContent = message;
    el.appendChild(title);
    el.appendChild(body);
    if (retry) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn";
      button.textContent = "重试";
      button.addEventListener("click", retry);
      el.appendChild(button);
    }
  }

  function clearAlert(key) {
    setAlert(key, null, null, null);
  }

  function setComputeState(id, text, kind) {
    var el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "compute-state" + (kind ? " is-" + kind : "");
  }

  function stamp() {
    return new Date().toLocaleTimeString("zh-CN", { hour12: false });
  }

  function setGlobalAlert(kind, message, retry) {
    var el = $("global-alert");
    if (!el) return;
    clearNode(el);
    if (!message) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.dataset.kind = kind || "error";
    var title = document.createElement("span");
    title.className = "alert-title";
    title.textContent = kind === "success" ? "已完成" : "提示";
    var body = document.createElement("span");
    body.className = "alert-message";
    body.textContent = message;
    el.appendChild(title);
    el.appendChild(body);
    if (retry) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn";
      button.textContent = "重试";
      button.addEventListener("click", retry);
      el.appendChild(button);
    }
  }

  /* ------------------------------------------------------------- charts */

  function chartFor(id) {
    if (!ECHARTS) return null;
    var el = $(id);
    if (!el || !el.offsetWidth || !el.offsetHeight) return null;
    var existing = charts.get(id);
    if (existing && !existing.isDisposed()) return existing;
    var instance = ECHARTS.init(el, null, { renderer: "canvas" });
    charts.set(id, instance);
    return instance;
  }

  function resizeCharts() {
    charts.forEach(function (chart) {
      if (chart && !chart.isDisposed()) chart.resize();
    });
  }

  function baseOption(extra) {
    var option = {
      backgroundColor: "transparent",
      textStyle: {
        color: C.creamDim,
        fontFamily:
          '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif',
        fontSize: 11
      },
      animationDuration: 420,
      grid: { left: 52, right: 24, top: 42, bottom: 38, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        borderWidth: 1,
        textStyle: { color: C.cream, fontSize: 11 },
        axisPointer: {
          lineStyle: { color: "rgba(233,162,59,0.45)" },
          crossStyle: { color: "rgba(233,162,59,0.45)" }
        }
      },
      legend: {
        top: 4,
        right: 8,
        itemWidth: 12,
        itemHeight: 9,
        itemGap: 12,
        textStyle: { color: C.creamDim, fontSize: 11 }
      }
    };
    if (extra) {
      Object.keys(extra).forEach(function (key) {
        if (key === "legend" && option.legend && extra.legend) {
          option.legend = Object.assign({}, option.legend, extra.legend);
        } else {
          option[key] = extra[key];
        }
      });
    }
    return option;
  }

  function axisStyle() {
    return {
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: C.grid, type: "dashed" } }
    };
  }

  function setChartOption(id, option) {
    var chart = chartFor(id);
    if (!chart) return;
    chart.setOption(option, true);
  }

  /* ------------------------------------------------------- tabs / init */

  function activate(target, options) {
    var opts = options || {};
    if (SECTIONS.indexOf(target) < 0) target = "overview";
    state.active = target;
    SECTIONS.forEach(function (id) {
      var section = $(id);
      if (section) section.hidden = id !== target;
    });
    document.querySelectorAll(".nav-item").forEach(function (button) {
      var active = button.getAttribute("data-target") === target;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    if (opts.scroll !== false && typeof history !== "undefined" && history.replaceState) {
      history.replaceState(null, "", "#" + target);
    }
    if (opts.scroll !== false) window.scrollTo({ top: 0, behavior: "auto" });

    requestAnimationFrame(function () {
      resizeCharts();
      if (target === "model1" && state.model1) renderModel1Chart(state.model1);
      if (target === "model2" && state.model2) renderModel2Chart(state.model2);
      if (target === "model3" && state.model3) {
        renderModel3Charts(state.model3);
      }
      if (target === "history" && state.history) renderHistoryCharts();
    });

    if (target === "model3" && !state.computed.model3) runModel3();
    if (target === "history" && !state.history) runHistory();
  }

  function bindNav() {
    document.querySelectorAll(".nav-item").forEach(function (button) {
      button.addEventListener("click", function () {
        activate(button.getAttribute("data-target"));
      });
    });
  }

  /* ------------------------------------------------------------ overview */

  function setBadge(id, text, modifier) {
    var el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "badge" + (modifier ? " " + modifier : "");
  }

  function renderStatus(overview) {
    var status = overview && overview.status ? overview.status : {};
    var count = toNum(status.count);
    setText("status-count", count === null ? "—" : fmtInt(count) + " 期");
    setText("status-issue", status.latest_issue || "—");
    setText("status-date", status.latest_date || "");
    setText("status-pool", fmtMoney(status.latest_pool));
    if (status.offline) {
      setBadge("status-source", "离线样例", "badge--offline");
    } else {
      var source = String(status.source || "本地缓存");
      if (/500\.com/i.test(source)) {
        source = "500.com";
      } else if (/^https?:\/\//i.test(source)) {
        try {
          source = new URL(source).hostname.replace(/^www\./, "");
        } catch (ignore) {
          /* 保留原始字符串 */
        }
      }
      setBadge("status-source", source, "badge--teal");
      var sourceBadge = $("status-source");
      if (sourceBadge) sourceBadge.title = String(status.source || source);
    }
    var fetched = status.fetched_at ? String(status.fetched_at) : "";
    if (fetched) {
      var parsed = new Date(fetched);
      setText(
        "status-fetched",
        isNaN(parsed.getTime())
          ? fetched
          : "同步于 " +
              parsed.toLocaleString("zh-CN", {
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false
              })
      );
    } else {
      setText("status-fetched", "尚未同步");
    }
  }

  function renderBalls(groupId, numbers, isBack) {
    var group = $(groupId);
    if (!group) return;
    clearNode(group);
    asArray(numbers).forEach(function (value) {
      var ball = document.createElement("span");
      ball.className = "ball" + (isBack ? " ball--back" : "");
      ball.textContent = String(value).padStart(2, "0");
      group.appendChild(ball);
    });
    if (!group.children.length) {
      var empty = document.createElement("span");
      empty.className = "mono";
      empty.style.color = C.muted2;
      empty.textContent = "—";
      group.appendChild(empty);
    }
  }

  function renderOverview(data) {
    state.overview = data;
    renderStatus(data);
    var key = data.key_numbers || {};
    var total = pickNum(key, ["total_combos", "total"]);
    var jackpotProb = pickNum(key, ["jackpot_probability", "jackpot_prob"]);
    var winCombos = pickNum(key, ["any_prize_combos", "winning_combos"]);
    var anyRate = pickNum(key, ["any_prize_rate", "any_rate"]);
    var returnRate = pickNum(key, ["return_rate"]);
    var ticketPrice = pickNum(key, ["ticket_price"]);

    setText("key-total-combos", total === null ? "21,425,712" : fmtInt(total));
    setText(
      "key-jackpot-prob",
      jackpotProb === null ? "1 / 21,425,712" : fmtOneIn(jackpotProb)
    );
    setNote(
      "key-jackpot-prob",
      jackpotProb === null ? "约 4.667×10⁻⁸" : "约 " + fmtSci(jackpotProb, 3)
    );
    setText("key-win-combos", winCombos === null ? "1,429,197" : fmtInt(winCombos));
    setText("key-any-rate", anyRate === null ? "6.67%" : fmtPct(anyRate, 2));
    setText(
      "key-return-rate",
      returnRate === null ? "51%" : fmtPct(returnRate, 0)
    );
    setText(
      "key-ticket-price",
      ticketPrice === null ? "2 元" : trimFixed(ticketPrice, 2) + " 元"
    );

    var latest = data.latest || {};
    setText("latest-issue", latest.issue || "—");
    setText("latest-date", latest.date || "—");
    setText("latest-pool", fmtMoney(latest.pool));
    renderBalls("latest-front", latest.front, false);
    renderBalls("latest-back", latest.back, true);

    var count = toNum(data.status && data.status.count);
    var spanText =
      "2007 年上市至今共 " +
      (count === null ? "约 2951" : fmtInt(count)) +
      " 期历史开奖。每一期相互独立，样本再大也不会让下一期“更容易中”。";
    setText("data-span-note", spanText);

    var basis = total === null ? 21425712 : total;
    setText("coin-24-prob", "1 / " + fmtInt(Math.pow(2, 24)));
    setText("coin-count", trimFixed(Math.log2(basis), 2));
    var jackpotBar = $("coin-bar-jackpot");
    if (jackpotBar) {
      var ratio = Math.min(100, Math.max(8, (Math.pow(2, 24) / basis) * 100));
      jackpotBar.style.width = trimFixed(ratio, 1) + "%";
      jackpotBar.style.setProperty("--w", trimFixed(ratio, 1) + "%");
    }

    updateBudget();
  }

  async function loadOverview() {
    try {
      var data = await getJSON("/api/overview");
      renderOverview(data);
      setGlobalAlert(null);
      if (!state.computed.model1) runModel1();
      if (!state.computed.model2) runModel2();
    } catch (error) {
      renderStatus(null);
      setGlobalAlert(
        "error",
        "无法读取概览数据：" + errorMessage(error),
        loadOverview
      );
    }
  }

  async function refreshData() {
    var button = $("refresh-btn");
    var label = $("refresh-label");
    if (button) button.disabled = true;
    if (label) label.textContent = "刷新中…";
    if (button) button.classList.add("is-busy");
    setGlobalAlert(null);
    try {
      var result = await postJSON("/api/data/refresh", {}, 90000);
      await loadOverview();
      runModel1();
      runModel2();
      if (state.computed.model3) runModel3();
      if (state.computed.history) runHistory();
      var added = toNum(result && result.added);
      var total = toNum(result && result.total);
      setGlobalAlert(
        "success",
        "数据已更新：" +
          (added === null ? "新增期数未知" : "新增 " + fmtInt(added) + " 期") +
          (total === null ? "" : "，当前共 " + fmtInt(total) + " 期") +
          "。"
      );
      if (label) label.textContent = "已刷新";
    } catch (error) {
      setGlobalAlert("error", "刷新失败：" + errorMessage(error), refreshData);
      if (label) label.textContent = "刷新数据";
    } finally {
      if (button) button.disabled = false;
      if (button) button.classList.remove("is-busy");
      setTimeout(function () {
        if (label) label.textContent = "刷新数据";
      }, 1600);
    }
  }

  /* -------------------------------------------------------------- budget */

  function updateBudget() {
    var input = $("budget-input");
    if (!input) return;
    var budget = toNum(input.value);
    if (budget === null || budget < 0) budget = 0;
    var key = (state.overview && state.overview.key_numbers) || {};
    var price = pickNum(key, ["ticket_price"]) || 2;
    var jackpotProb = pickNum(key, ["jackpot_probability"]) || 1 / 21425712;
    var anyRate = pickNum(key, ["any_prize_rate"]) || 1429197 / 21425712;
    var tickets = Math.floor(budget / price);

    setText("budget-tickets", fmtInt(tickets) + " 注");
    setText("budget-loss", fmtMoney(budget * 0.49));

    var jackpotChance = atLeastOnce(jackpotProb, tickets);
    if (tickets <= 0) {
      setText("budget-jackpot", "—");
      setText("budget-any", "—");
    } else {
      setText("budget-jackpot", fmtSci(jackpotChance, 3));
      setText("budget-any", fmtPct(atLeastOnce(anyRate, tickets), 3));
    }
  }

  function bindBudget() {
    var input = $("budget-input");
    if (!input) return;
    input.addEventListener("input", debounce(updateBudget, 150));
  }

  function numOf() {
    for (var i = 0; i < arguments.length; i += 1) {
      var n = toNum(arguments[i]);
      if (n !== null) return n;
    }
    return null;
  }

  function fmtMoneySmall(value) {
    var n = toNum(value);
    if (n === null) return "—";
    if (n !== 0 && Math.abs(n) < 0.001) return fmtSci(n, 3) + " 元";
    return trimFixed(n, 4) + " 元";
  }

  function setTone(id, tone) {
    var el = $(id);
    if (!el) return;
    el.classList.remove("is-negative", "is-neutral", "is-teal");
    if (tone) el.classList.add("is-" + tone);
  }

  /* -------------------------------------------------------------- model 1 */

  function readNumber(id, fallback) {
    var el = $(id);
    if (!el) return fallback;
    var n = toNum(el.value);
    return n === null ? fallback : n;
  }

  function poolFromSelect(selectId) {
    var el = $(selectId);
    var value = el ? el.value : "auto";
    if (value === "high") return 900000000;
    if (value === "normal") return 0;
    return null;
  }

  function extractTiers(data, rules) {
    var candidates = [
      data && data.tiers,
      data && data.rules && data.rules.tiers,
      data && data.rules && data.rules.breakdown,
      data && data.breakdown,
      rules && rules.tiers,
      rules && rules.breakdown,
      rules && rules.rule_table
    ];
    for (var i = 0; i < candidates.length; i += 1) {
      if (Array.isArray(candidates[i]) && candidates[i].length) return candidates[i];
    }
    return [];
  }

  async function ensureRules(pool, mode) {
    var key = String(pool) + "|" + String(mode);
    if (state.rules && state.rulesKey === key) return state.rules;
    try {
      var url = "/api/rules?mode=" + encodeURIComponent(mode || "rules");
      if (pool !== null && pool !== undefined) {
        url += "&pool=" + encodeURIComponent(pool);
      }
      var data = await getJSON(url, 12000);
      state.rules = data;
      state.rulesKey = key;
      return data;
    } catch (error) {
      return null;
    }
  }

  function tierName(tier, index) {
    var name = pick(
      tier,
      ["label", "name", "title", "level", "tier"],
      null
    );
    if (name === null || name === undefined) return "第 " + (index + 1) + " 奖级";
    if (typeof name === "number") return "第 " + name + " 奖级";
    var text = String(name);
    if (/^\d+$/.test(text)) return "第 " + text + " 奖级";
    return text;
  }

  function renderTierTable(tiers) {
    var body = $("m1-tier-body");
    if (!body) return;
    clearNode(body);
    if (!tiers.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 6;
      emptyCell.className = "table-empty";
      emptyCell.textContent = "奖级数据加载中或暂不可用…";
      emptyRow.appendChild(emptyCell);
      body.appendChild(emptyRow);
      return;
    }
    tiers.forEach(function (tier, index) {
      var row = document.createElement("tr");
      var nameCell = document.createElement("td");
      nameCell.className = "tier-name" + (index === 0 ? " tier-first" : "");
      nameCell.textContent = tierName(tier, index);
      row.appendChild(nameCell);

      var conditionCell = document.createElement("td");
      var condition = pick(
        tier,
        [
          "condition_text",
          "condition",
          "conditions",
          "match",
          "desc",
          "description",
          "hit"
        ],
        "—"
      );
      conditionCell.textContent = Array.isArray(condition)
        ? condition.join(" / ")
        : String(condition);
      row.appendChild(conditionCell);

      var combosCell = document.createElement("td");
      combosCell.className = "num";
      var combos = pickNum(tier, ["combos", "combinations", "count", "ways"]);
      combosCell.textContent = combos === null ? "—" : fmtInt(combos);
      row.appendChild(combosCell);

      var probCell = document.createElement("td");
      probCell.className = "num";
      var prob = pickNum(tier, ["probability", "p", "rate", "odds"]);
      if (prob === null) {
        var rawProb = pick(tier, ["probability", "p", "rate", "odds"], null);
        probCell.textContent = rawProb === null ? "—" : String(rawProb);
      } else {
        probCell.textContent =
          prob < 1e-4 ? fmtSci(prob, 3) : fmtPct(prob, 4);
      }
      row.appendChild(probCell);

      var amountCell = document.createElement("td");
      amountCell.className = "num";
      var amount = pickNum(tier, [
        "amount",
        "prize",
        "bonus",
        "fixed_amount",
        "prize_amount"
      ]);
      amountCell.textContent = amount === null ? "浮动" : fmtMoney(amount);
      row.appendChild(amountCell);

      var evCell = document.createElement("td");
      evCell.className = "num";
      var ev = pickNum(tier, [
        "ev_contribution",
        "ev",
        "expected",
        "expected_value",
        "contribution"
      ]);
      evCell.textContent = ev === null ? "—" : fmtMoneySmall(ev);
      row.appendChild(evCell);

      body.appendChild(row);
    });
  }

  function renderTierChart(tiers) {
    if (!tiers || !tiers.length) {
      setChartOption("chart-m1-tier", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "等待奖级概率数据…", fill: C.muted2, fontSize: 12 }
        }
      });
      return;
    }
    var labels = [];
    var values = [];
    tiers.forEach(function (tier, index) {
      labels.push(tierName(tier, index));
      values.push(pickNum(tier, ["probability", "p", "rate", "odds"]));
    });
    var categories = labels.slice().reverse();
    var data = values
      .slice()
      .reverse()
      .map(function (prob, index) {
        return {
          value: prob,
          itemStyle: { color: index === values.length - 1 ? C.red : C.teal }
        };
      });

    var option = baseOption({
      grid: { left: 64, right: 104, top: 18, bottom: 30, containLabel: true },
      legend: { show: false },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var prob = params[0].value;
          return (
            params[0].name +
            "<br/>概率 " +
            fmtPct(prob, 4) +
            "（" +
            fmtOneIn(prob) +
            "）"
          );
        }
      },
      xAxis: Object.assign(
        {
          type: "log",
          min: 1e-8,
          max: 0.2,
          name: "概率（对数刻度）",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: {
            color: C.muted2,
            fontSize: 8,
            formatter: function (value) {
              return fmtSci(value, 0);
            }
          }
        },
        axisStyle()
      ),
      yAxis: {
        type: "category",
        data: categories,
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.creamDim, fontSize: 10 }
      },
      series: [
        {
          name: "中奖概率",
          type: "bar",
          data: data,
          barMaxWidth: 15,
          label: {
            show: true,
            position: "right",
            color: C.creamDim,
            fontSize: 9,
            formatter: function (params) {
              return fmtOneIn(params.value);
            }
          }
        }
      ]
    });
    setChartOption("chart-m1-tier", option);
  }

  function model1Body() {
    var jackpotWan = Math.max(0, readNumber("m1-jackpot", 500));
    var secondWan = Math.max(0, readNumber("m1-second", 10));
    var mode = ($("m1-mode") && $("m1-mode").value) || "rules";
    return {
      jackpot: jackpotWan * 10000,
      second_prize: secondWan * 10000,
      pool: poolFromSelect("m1-pool"),
      price: 2,
      mode: mode
    };
  }

  async function runModel1() {
    var token = ++seq.model1;
    var body = model1Body();
    setComputeState("m1-state", "计算中…", "busy");
    try {
      var data = await postJSON("/api/model1", body, 15000);
      if (token !== seq.model1) return;
      if (!extractTiers(data).length) {
        var rules = await ensureRules(body.pool, body.mode);
        if (rules) data._tiers = extractTiers(data, rules);
      }
      state.model1 = data;
      state.computed.model1 = true;
      renderModel1(data);
      clearAlert("model1");
      setComputeState("m1-state", "已更新 " + stamp(), "ok");
    } catch (error) {
      if (token !== seq.model1) return;
      if (error.status === 503) {
        setComputeState("m1-state", "模型模块加载中", "busy");
        setAlert(
          "model1",
          "loading",
          "模型模块加载中：后端计算模块尚未就绪。稍后重试，页面其他部分仍可浏览。",
          runModel1
        );
      } else {
        setComputeState("m1-state", "计算失败", "error");
        setAlert("model1", "error", errorMessage(error), runModel1);
      }
    }
  }

  function renderModel1(data) {
    var rules = data.rules || {};
    var kelly = data.kelly || {};
    var ev = numOf(data.display_ev, rules.ev);
    var payout = numOf(data.display_payout_rate, rules.payout_rate);
    var fstar = numOf(kelly.f_star);
    var fraw = numOf(kelly.f_star_raw);
    var pb = numOf(kelly.p_b);
    if (pb === null) {
      var p = numOf(kelly.p);
      var b = numOf(kelly.b);
      if (p !== null && b !== null) pb = p * b;
    }
    var critical = numOf(kelly.critical_jackpot);
    var capBasic = numOf(kelly.cap_basic);
    var capAddon = numOf(kelly.cap_addon);
    var overviewKey = (state.overview && state.overview.key_numbers) || {};
    if (capBasic === null) capBasic = pickNum(overviewKey, ["jackpot_cap_basic"]);
    if (capAddon === null) capAddon = pickNum(overviewKey, ["jackpot_cap_addon"]);
    var multiple = numOf(kelly.critical_multiple);
    if (multiple === null && critical !== null && capBasic) {
      multiple = critical / capBasic;
    }

    setText("m1-ev", ev === null ? "—" : fmtMoneySigned(ev));
    setTone("m1-ev", ev !== null && ev < 0 ? "negative" : "neutral");
    setNote(
      "m1-ev",
      ev === null
        ? "每投入 2 元的平均回报"
        : "每投入 2 元，长期平均" + (ev < 0 ? "亏损 " : "回报 ") + fmtMoney(Math.abs(ev))
    );

    setText("m1-payout", payout === null ? "—" : fmtPct(payout, 2));
    setText("m1-fstar", fstar === null ? "—" : fmtPct(fstar, 4));
    setTone("m1-fstar", fstar !== null && fstar > 0 ? "teal" : "negative");
    setText("m1-fraw", fraw === null ? "—" : fmtSci(fraw, 3));
    setText("m1-pb", pb === null ? "—" : fmtRatio(pb));
    setText("m1-critical", critical === null ? "—" : fmtMoney(critical));
    setText(
      "m1-cap",
      capBasic === null
        ? "—"
        : fmtMoney(capBasic) + (capAddon === null ? "" : " / " + fmtMoney(capAddon))
    );
    setText("m1-multiple", multiple === null ? "—" : trimFixed(multiple, 2) + "×");

    var mode = data.mode || (($("m1-mode") && $("m1-mode").value) || "rules");
    var poolMode =
      data.pool_mode ||
      (state.overview && state.overview.pool_mode) ||
      "normal";
    var modeLabel =
      data.display_label || (mode === "video" ? "视频口径" : "当前规则");
    setText(
      "m1-mode-note",
      modeLabel + " · " + (poolMode === "high" ? "奖池 ≥ 8 亿" : "奖池 < 8 亿")
    );

    var multi = data.multi_tier || {};
    if (multi.verdict) {
      setText("m1-multi-verdict", String(multi.verdict));
    } else if (multi.rules_slope !== undefined || multi.statutory_slope !== undefined) {
      setText(
        "m1-multi-verdict",
        "多奖级斜率：规则明细 " +
          trimFixed(multi.rules_slope, 4) +
          "，返奖率口径 " +
          trimFixed(multi.statutory_slope, 4) +
          "；均为负，最优仓位为 0。"
      );
    }

    var verdict = pick(data, ["verdict", "display_label"], null);
    if (verdict === null) {
      verdict =
        fstar !== null && fstar > 0
          ? "凯利仓位为正，但请先核对假设；现实中仍需考虑封顶与分奖。"
          : "最优仓位为 0：不投。负期望不会因为注额小或次数少而变成正期望。";
    }
    var verdictText = String(verdict);
    if (verdictText.length <= 10) {
      verdictText +=
        " —— 单注期望 " +
        (ev === null ? "为负" : fmtMoneySigned(ev)) +
        "，凯利最优仓位 0，长期不投。";
    }
    var verdictEl = $("m1-verdict");
    if (verdictEl) verdictEl.textContent = verdictText;

    var tiers =
      Array.isArray(data._tiers) && data._tiers.length
        ? data._tiers
        : extractTiers(data);
    renderTierTable(tiers);
    renderTierChart(tiers);
    renderModel1Chart(data);
    renderNotes("m1-notes", data.notes, [
      "规则明细口径：逐奖级计算“概率 × 奖金”，再求和。",
      "返奖率口径：单注成本 × 51%，用于快速校验。",
      "两种口径都指向同一个结论：期望为负，最优仓位为 0。"
    ]);
  }

  function normalizePairs(list) {
    var result = [];
    asArray(list).forEach(function (item) {
      var f = null;
      var g = null;
      if (Array.isArray(item)) {
        f = toNum(item[0]);
        g = toNum(item[1]);
      } else if (item && typeof item === "object") {
        f = numOf(item.f, item.x, item.ratio);
        g = numOf(item.g, item.y, item.growth);
      }
      if (f !== null && g !== null && f >= 0 && f <= 1) result.push([f, g]);
    });
    result.sort(function (a, b) {
      return a[0] - b[0];
    });
    return result;
  }

  function synthGrowth(data) {
    var kelly = data.kelly || {};
    var p = numOf(kelly.p);
    var b = numOf(kelly.b);
    if (p === null || b === null || b <= 0) return [];
    var q = 1 - p;
    var curve = [];
    for (var i = 0; i <= 100; i += 1) {
      var f = i / 100;
      if (f >= 1) continue;
      var g = p * Math.log(1 + f * b) + q * Math.log(1 - f);
      if (isFinite(g)) curve.push([f, g]);
    }
    return curve;
  }

  function renderModel1Chart(data) {
    var growth = data.growth || {};
    var curve = normalizePairs(growth.curve);
    if (!curve.length) curve = synthGrowth(data);
    var points = normalizePairs(growth.points);
    var marks = [0.001, 0.01, 0.05, 0.5];
    var labelPositions = [
      "insideEndBottom",
      "insideEndTop",
      "insideEndBottom",
      "insideEndTop"
    ];
    var markLines = marks.map(function (value, index) {
      return {
        xAxis: value,
        lineStyle: { color: "rgba(57,181,165,0.45)", type: "dashed", width: 1 },
        label: {
          formatter: trimFixed(value * 100, value < 0.01 ? 1 : 0) + "%",
          color: C.teal,
          fontSize: 9,
          position: labelPositions[index] || "insideEndTop"
        }
      };
    });
    markLines.push({
      xAxis: 1,
      lineStyle: { color: "rgba(228,87,46,0.55)", type: "dashed", width: 1 },
      label: {
        formatter: "100%",
        color: C.red,
        fontSize: 9,
        position: "insideStartTop"
      }
    });

    var option = baseOption({
      grid: { left: 54, right: 26, top: 30, bottom: 44, containLabel: true },
      legend: { show: false },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var item = params[0];
          var f = item.value[0];
          var g = item.value[1];
          return (
            "下注比例 f = " +
            trimFixed(f * 100, 2) +
            "%<br>对数增长率 g = " +
            fmtPct(g, 3)
          );
        }
      },
      xAxis: Object.assign(
        {
          type: "value",
          min: 0,
          max: 1,
          name: "下注比例 f",
          nameTextStyle: { color: C.muted2, fontSize: 9, padding: [0, 0, 4, 0] },
          axisLabel: {
            color: C.muted2,
            fontSize: 9,
            formatter: function (value) {
              return trimFixed(value * 100, value * 100 < 10 ? 1 : 0) + "%";
            }
          }
        },
        axisStyle()
      ),
      yAxis: Object.assign(
        {
          type: "value",
          name: "g(f)",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: {
            color: C.muted2,
            fontSize: 9,
            formatter: function (value) {
              return trimFixed(value * 100, 1) + "%";
            }
          }
        },
        axisStyle()
      ),
      series: [
        {
          name: "g(f)",
          type: "line",
          data: curve,
          showSymbol: false,
          lineStyle: { color: C.amber, width: 2 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(233,162,59,0.16)" },
                { offset: 1, color: "rgba(233,162,59,0.01)" }
              ]
            }
          },
          markLine: {
            silent: true,
            symbol: ["none", "none"],
            data: [
              {
                yAxis: 0,
                lineStyle: { color: "rgba(242,234,217,0.4)", width: 1 },
                label: { formatter: "g = 0", color: C.creamDim, fontSize: 9 }
              }
            ].concat(markLines)
          }
        },
        {
          name: "关键点",
          type: "scatter",
          data: points,
          symbolSize: 6,
          itemStyle: { color: C.teal },
          tooltip: {
            formatter: function (params) {
              return (
                "f = " +
                trimFixed(params.value[0] * 100, 2) +
                "%<br>g = " +
                fmtPct(params.value[1], 3)
              );
            }
          }
        }
      ]
    });
    setChartOption("chart-m1-growth", option);
  }

  function renderNotes(containerId, notes, fallback) {
    var container = $(containerId);
    if (!container) return;
    clearNode(container);
    var list = Array.isArray(notes) ? notes.slice() : [];
    if (!list.length && Array.isArray(fallback)) list = fallback.slice();
    if (!list.length) return;
    var ul = document.createElement("ul");
    list.forEach(function (note) {
      var li = document.createElement("li");
      if (note && typeof note === "object") {
        li.textContent = String(
          pick(note, ["text", "message", "note", "detail"], JSON.stringify(note))
        );
      } else {
        li.textContent = String(note);
      }
      ul.appendChild(li);
    });
    container.appendChild(ul);
  }

  function bindModel1() {
    var handler = debounce(runModel1, 300);
    ["m1-jackpot", "m1-second", "m1-pool", "m1-mode"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
  }

  /* -------------------------------------------------------------- model 2 */

  function model2Body() {
    return {
      jackpot: Math.max(0, readNumber("m2-jackpot", 500)) * 10000,
      second_prize: Math.max(0, readNumber("m2-second", 10)) * 10000,
      pool: null,
      tickets_per_sec: Math.max(0.01, readNumber("m2-tps", 1))
    };
  }

  async function runModel2() {
    var token = ++seq.model2;
    setComputeState("m2-state", "计算中…", "busy");
    try {
      var data = await postJSON("/api/model2", model2Body(), 15000);
      if (token !== seq.model2) return;
      state.model2 = data;
      state.computed.model2 = true;
      renderModel2(data);
      clearAlert("model2");
      setComputeState("m2-state", "已更新 " + stamp(), "ok");
    } catch (error) {
      if (token !== seq.model2) return;
      if (error.status === 503) {
        setComputeState("m2-state", "模型模块加载中", "busy");
        setAlert(
          "model2",
          "loading",
          "模型模块加载中：后端计算模块尚未就绪。稍后重试，页面其他部分仍可浏览。",
          runModel2
        );
      } else {
        setComputeState("m2-state", "计算失败", "error");
        setAlert("model2", "error", errorMessage(error), runModel2);
      }
    }
  }

  function renderModel2(data) {
    var cost = data.cost || {};
    var rebate = data.rebate || {};
    var cap = data.cap || {};
    var printing = data.printing || {};
    var amount = numOf(cost.amount, data.cost_amount, data.total_cost);
    var fixed = numOf(rebate.fixed);
    var second = numOf(rebate.second);
    var jackpotRebate = numOf(rebate.jackpot);
    var totalIncome = numOf(rebate.total, data.total_income);
    var net = numOf(data.net, data.profit);
    if (totalIncome === null && amount !== null && net !== null) {
      totalIncome = amount + net;
    }
    var breakEven = numOf(data.break_even_jackpot, data.breakeven_jackpot);
    var gapBasic = numOf(cap.gap_to_basic);
    var gapAddon = numOf(cap.gap_to_addon);
    var capBasic = numOf(cap.basic);
    if (gapBasic === null && breakEven !== null && capBasic !== null) {
      gapBasic = breakEven - capBasic;
    }

    setText("m2-cost", fmtMoney(amount));
    setNote(
      "m2-cost",
      amount === null
        ? "21,425,712 注 × 2 元"
        : fmtInt(cost.total_combos || 21425712) + " 注 × " + trimFixed(cost.price || 2, 2) + " 元"
    );
    setText("m2-fixed", fmtMoney(fixed));
    setText("m2-second-rebate", fmtMoney(second));
    setText("m2-total-income", fmtMoney(totalIncome));
    setText("m2-net", net === null ? "—" : fmtMoneySigned(net));
    setTone("m2-net", net !== null && net < 0 ? "negative" : "teal");
    setText("m2-breakeven", fmtMoney(breakEven));
    setText("m2-gap", gapBasic === null ? "—" : fmtMoneySigned(gapBasic));
    setTone("m2-gap", gapBasic !== null && gapBasic > 0 ? "negative" : "teal");

    var seconds = numOf(printing.seconds);
    var days = numOf(printing.days);
    if (days !== null) {
      setText("m2-days", trimFixed(days, 1) + " 天");
    } else {
      setText("m2-days", fmtDay(seconds));
    }
    var tickets = numOf(printing.tickets, cost.total_combos);
    setNote(
      "m2-days",
      tickets === null
        ? "按输入速度连续出票"
        : fmtInt(tickets) +
            " 注 ÷ " +
            trimFixed(printing.tickets_per_sec || 1, 2) +
            " 注/秒"
    );

    var verdict = pick(data, ["verdict"], null);
    if (verdict === null) {
      verdict =
        gapBasic !== null && gapBasic > 0
          ? "不适用：盈亏平衡头奖高于单注封顶，全包号无法稳定盈利。"
          : "需结合封顶、分奖与出票时间综合判断。";
    }
    var verdictText = String(verdict);
    if (verdictText.length <= 10) {
      verdictText +=
        " —— 盈亏平衡头奖 " +
        (breakEven === null ? "未知" : fmtMoney(breakEven)) +
        "，单注封顶 " +
        (capBasic === null ? "未知" : fmtMoney(capBasic)) +
        (gapBasic === null ? "。" : "，缺口 " + fmtMoney(gapBasic) + "。");
    }
    var verdictEl = $("m2-verdict");
    if (verdictEl) {
      verdictEl.textContent = verdictText;
      verdictEl.className =
        "verdict-line " +
        (gapBasic !== null && gapBasic > 0 ? "verdict-line--amber" : "");
    }

    renderModel2Chart(data);
    renderNotes("m2-notes", data.reasons || data.notes, [
      "全包号假设你能独中头奖、无多人分奖，并且能在销售窗口内完成出票。",
      "固定奖回血与二等奖回血都是你自己买出来的奖金，不是额外收益。",
      "单注封顶使盈亏平衡头奖无法兑现，策略在当前规则下不成立。"
    ]);
  }

  function renderModel2Chart(data) {
    var cost = data.cost || {};
    var rebate = data.rebate || {};
    var amount = numOf(cost.amount, data.cost_amount, data.total_cost);
    var fixed = numOf(rebate.fixed) || 0;
    var second = numOf(rebate.second) || 0;
    var jackpot = numOf(rebate.jackpot) || 0;
    var net = numOf(data.net);
    var residual =
      amount === null
        ? 0
        : Math.max(0, amount - fixed - second - jackpot);
    if (amount === null) {
      setChartOption("chart-m2-cost", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "等待成本数据…", fill: C.muted2, fontSize: 12 }
        }
      });
      return;
    }

    var caption = "全包成本 " + fmtMoney(amount) + "：";
    caption += "固定奖回血 " + fmtMoney(fixed) + "，二等奖回血 " + fmtMoney(second);
    if (jackpot) caption += "，头奖回血 " + fmtMoney(jackpot);
    caption += "，剩余 " + fmtMoney(residual) + " 是填不平的净亏损。";
    setText("m2-cost-caption", caption);

    var stackTotal = fixed + second + jackpot + residual;

    var option = baseOption({
      grid: { left: 16, right: 20, top: 38, bottom: 42, containLabel: true },
      legend: { top: 0, right: 0, left: "auto" },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var lines = [params[0].axisValue];
          params.forEach(function (item) {
            lines.push(
              item.marker + item.seriesName + "：" + fmtMoney(item.value)
            );
          });
          lines.push("<br>合计：" + fmtMoney(amount));
          return lines.join("<br>");
        }
      },
      xAxis: Object.assign(
        {
          type: "value",
          max: Math.max(amount, stackTotal),
          axisLabel: {
            color: C.muted2,
            fontSize: 9,
            formatter: function (value) {
              if (Math.abs(value) >= 1e8) return trimFixed(value / 1e8, 1) + " 亿";
              return trimFixed(value / 1e4, 0) + " 万";
            }
          }
        },
        axisStyle()
      ),
      yAxis: {
        type: "category",
        data: ["全包成本"],
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.muted, fontSize: 10 }
      },
      series: [
        {
          name: "固定奖回血",
          type: "bar",
          stack: "cost",
          data: [fixed],
          itemStyle: { color: C.teal },
          barWidth: 42
        },
        {
          name: "二等奖回血",
          type: "bar",
          stack: "cost",
          data: [second],
          itemStyle: { color: C.steel }
        },
        {
          name: "头奖回血",
          type: "bar",
          stack: "cost",
          data: [jackpot],
          itemStyle: { color: C.amber }
        },
        {
          name: net !== null && net > 0 ? "净收益" : "净亏损",
          type: "bar",
          stack: "cost",
          data: [residual],
          itemStyle: { color: C.red },
          label: {
            show: true,
            color: C.cream,
            fontSize: 10,
            formatter: function () {
              return residual > 0 ? fmtMoney(residual) : "";
            }
          }
        }
      ]
    });
    setChartOption("chart-m2-cost", option);
  }

  function bindModel2() {
    var handler = debounce(runModel2, 300);
    ["m2-jackpot", "m2-second", "m2-tps"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
  }

  /* -------------------------------------------------------------- model 3 */

  function model3Body() {
    var pct = readNumber("m3-pwin", 6.67);
    return {
      base_bet: Math.max(0.01, readNumber("m3-base", 2)),
      multiplier: Math.max(1.01, readNumber("m3-mult", 2)),
      bankroll: Math.max(1, readNumber("m3-bankroll", 10000)),
      rounds: Math.round(Math.min(1000, Math.max(1, readNumber("m3-rounds", 100)))),
      simulations: Math.round(
        Math.min(5000, Math.max(100, readNumber("m3-sims", 1000)))
      ),
      p_win: Math.min(1, Math.max(0, pct / 100)),
      seed: 42
    };
  }

  async function runModel3() {
    var token = ++seq.model3;
    setComputeState("m3-state", "模拟计算中…", "busy");
    try {
      var data = await postJSON("/api/model3", model3Body(), 30000);
      if (token !== seq.model3) return;
      state.model3 = data;
      state.computed.model3 = true;
      renderModel3(data);
      clearAlert("model3");
      setComputeState("m3-state", "已更新 " + stamp(), "ok");
    } catch (error) {
      if (token !== seq.model3) return;
      if (error.status === 503) {
        setComputeState("m3-state", "模型模块加载中", "busy");
        setAlert(
          "model3",
          "loading",
          "模型模块加载中：后端蒙特卡洛模块尚未就绪。稍后重试，页面其他部分仍可浏览。",
          runModel3
        );
      } else {
        setComputeState("m3-state", "计算失败", "error");
        setAlert("model3", "error", errorMessage(error), runModel3);
      }
    }
  }

  function deriveCapital(base, multiplier, k) {
    var invested;
    if (Math.abs(multiplier - 1) < 1e-9) {
      invested = base * k;
    } else {
      invested = (base * (Math.pow(multiplier, k) - 1)) / (multiplier - 1);
    }
    var next = base * Math.pow(multiplier, k);
    return { k: k, invested: invested, next_bet: next, total: invested + next };
  }

  function capitalRow(data, k) {
    var rows = asArray(data.full_table);
    if (!rows.length) rows = asArray(data.capital_table);
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      if (!row || typeof row !== "object") continue;
      var rowK = numOf(row.k, row.streak, row.losses, row.round);
      if (rowK !== null && Math.round(rowK) === k) return row;
    }
    if (rows.length >= k && rows[k - 1] && typeof rows[k - 1] === "object") {
      var indexed = rows[k - 1];
      if (numOf(indexed.invested, indexed.next_bet, indexed.total) !== null) {
        return indexed;
      }
    }
    var input = data.input || {};
    var base = numOf(input.base_bet) || 2;
    var multiplier = numOf(input.multiplier) || 2;
    return deriveCapital(base, multiplier, k);
  }

  function renderModel3(data) {
    var sim = data.simulation || {};
    var input = data.input || {};
    var ruin = numOf(sim.ruin_probability, sim.ruin_rate);
    var median = numOf(sim.median_ruin_round);
    var maxStreak = numOf(sim.max_streak_mean, sim.max_streak);
    var meanFinal = numOf(sim.mean_final_bankroll);

    if (ruin === null) {
      setText("m3-ruin", "—");
    } else {
      setText("m3-ruin", ruin > 1 ? fmtPct(ruin / 100, 1) : fmtPct(ruin, 1));
    }
    var ruinText =
      ruin === null ? "—" : ruin > 1 ? fmtPct(ruin / 100, 1) : fmtPct(ruin, 1);
    setTone("m3-ruin", "negative");
    setText(
      "m3-median",
      median === null || median <= 0 ? "未破产" : fmtInt(median) + " 轮"
    );
    setText(
      "m3-maxstreak",
      maxStreak === null ? "—" : trimFixed(maxStreak, 1) + " 次"
    );
    setText("m3-meanbank", fmtMoney(meanFinal));
    setTone("m3-meanbank", meanFinal !== null && meanFinal <= 0 ? "negative" : "neutral");

    var assumption = $("m3-assumption");
    if (assumption) {
      var text = assumption.querySelector("span");
      if (text && sim.assumption) {
        text.textContent = String(sim.assumption).replace(
          /^理想化(?:假设)?[：:]\s*/,
          ""
        );
      }
    }

    var rounds = Math.round(numOf(input.rounds) || 100);
    var simulations =
      numOf(sim.params && sim.params.simulations, input.simulations) || null;
    setText(
      "m3-path-note",
      (simulations === null ? "" : fmtInt(simulations) + " 次 × ") +
        fmtInt(rounds) +
        " 轮"
    );

    var body = $("m3-table-body");
    if (body) {
      clearNode(body);
      [10, 16, 20].forEach(function (k) {
        var row = capitalRow(data, k);
        var tr = document.createElement("tr");
        var cells = [
          { text: "连黑 " + k + " 次", className: "tier-name" },
          { text: fmtMoney(numOf(row.invested)), className: "num" },
          { text: fmtMoney(numOf(row.next_bet)), className: "num" },
          { text: fmtMoney(numOf(row.total)), className: "num" }
        ];
        cells.forEach(function (cell) {
          var td = document.createElement("td");
          td.className = cell.className;
          td.textContent = cell.text;
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }

    var verdict = pick(data, ["verdict"], null);
    if (verdict === null || verdict === undefined) {
      verdict = "负期望游戏中，倍投只改变亏损路径，不改变期望；有限本金下破产概率随轮数趋近 1。";
    }
    var verdictText = String(verdict);
    if (verdictText.length <= 10) {
      verdictText +=
        " —— 破产概率 " +
        ruinText +
        "，平均最大连黑 " +
        (maxStreak === null ? "—" : trimFixed(maxStreak, 1) + " 次") +
        "，期望不因倍投改变。";
    }
    var verdictEl = $("m3-verdict");
    if (verdictEl) verdictEl.textContent = verdictText;

    renderModel3Charts(data);
    renderNotes("m3-notes", data.notes, [
      "已采用对倍投最有利的 1:1 回本假设；真实规则更不利。",
      "连黑 20 次需要约 419 万元，而单注胜率不会因连黑而上升。",
      "负期望游戏中，倍投只改变亏损路径，不改变期望。"
    ]);
  }

  function normalizePathData(raw) {
    return asArray(raw)
      .map(function (item) {
        if (Array.isArray(item)) {
          var round = toNum(item[0]);
          var value = toNum(item[1]);
          return round !== null && value !== null ? [round, value] : null;
        }
        if (item && typeof item === "object") {
          var r = numOf(item.round, item.r, item.x);
          var v = numOf(item.bankroll, item.value, item.y);
          if (r !== null && v !== null) return [r, v];
        }
        return null;
      })
      .filter(Boolean);
  }

  function renderModel3Charts(data) {
    var sim = data.simulation || {};
    var input = data.input || {};
    var paths = asArray(sim.sample_paths);
    var palette = [C.teal, C.amber, C.steel, C.red, C.creamDim];
    var rounds = Math.round(numOf(input.rounds) || 100);
    var bankroll = numOf(input.bankroll);

    if (paths.length) {
      var series = paths.slice(0, 8).map(function (path, index) {
        var points = normalizePathData(path && path.data);
        return {
          name: (path && path.name) || "路径 " + (index + 1),
          type: "line",
          data: points,
          showSymbol: false,
          smooth: false,
          lineStyle: {
            width: 1.3,
            opacity: 0.88,
            color: palette[index % palette.length]
          },
          emphasis: { focus: "series" }
        };
      });
      var pathOption = baseOption({
        grid: { left: 58, right: 24, top: 36, bottom: 44, containLabel: true },
        legend: { show: false },
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(8,13,22,0.96)",
          borderColor: "rgba(242,234,217,0.22)",
          textStyle: { color: C.cream, fontSize: 11 },
          formatter: function (params) {
            if (!params || !params.length) return "";
            var lines = ["第 " + params[0].axisValue + " 轮"];
            params.slice(0, 6).forEach(function (item) {
              lines.push(item.marker + item.seriesName + "：" + fmtMoney(item.value[1]));
            });
            return lines.join("<br>");
          }
        },
        xAxis: Object.assign(
          {
            type: "value",
            min: 0,
            max: rounds,
            name: "轮次",
            nameTextStyle: { color: C.muted2, fontSize: 9 },
            axisLabel: { color: C.muted2, fontSize: 9 }
          },
          axisStyle()
        ),
        yAxis: Object.assign(
          {
            type: "value",
            name: "本金（元）",
            nameTextStyle: { color: C.muted2, fontSize: 9 },
            axisLabel: {
              color: C.muted2,
              fontSize: 9,
              formatter: function (value) {
                if (Math.abs(value) >= 1e8) return trimFixed(value / 1e8, 1) + " 亿";
                if (Math.abs(value) >= 1e4) return trimFixed(value / 1e4, 1) + " 万";
                return trimFixed(value, 0);
              }
            }
          },
          axisStyle()
        ),
        series: series
      });
      if (bankroll !== null) {
        pathOption.series[0].markLine = {
          silent: true,
          symbol: ["none", "none"],
          lineStyle: { color: "rgba(242,234,217,0.35)", type: "dashed", width: 1 },
          label: {
            formatter: "初始本金",
            color: C.muted,
            fontSize: 9,
            position: "insideEndTop"
          },
          data: [{ yAxis: bankroll }]
        };
      }
      setChartOption("chart-m3-paths", pathOption);
    } else {
      setChartOption("chart-m3-paths", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "本次模拟未返回资金曲线", fill: C.muted2, fontSize: 12 }
        }
      });
    }

    var rows = [10, 16, 20].map(function (k) {
      return capitalRow(data, k);
    });
    var capitalOption = baseOption({
      grid: { left: 52, right: 20, top: 36, bottom: 38, containLabel: true },
      legend: { top: 0, right: 0, left: "auto" },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var lines = [params[0].axisValue];
          params.forEach(function (item) {
            lines.push(item.marker + item.seriesName + "：" + fmtMoney(item.value));
          });
          return lines.join("<br>");
        }
      },
      xAxis: {
        type: "category",
        data: ["连黑 10", "连黑 16", "连黑 20"],
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.muted, fontSize: 10 }
      },
      yAxis: Object.assign(
        {
          type: "log",
          min: 1,
          name: "元（对数）",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: {
            color: C.muted2,
            fontSize: 9,
            formatter: function (value) {
              if (value >= 1e8) return trimFixed(value / 1e8, 0) + "亿";
              if (value >= 1e4) return trimFixed(value / 1e4, 0) + "万";
              return trimFixed(value, 0);
            }
          }
        },
        axisStyle()
      ),
      series: [
        {
          name: "已投入",
          type: "bar",
          data: rows.map(function (row) {
            return Math.max(1, numOf(row.invested) || 1);
          }),
          itemStyle: { color: C.teal },
          barMaxWidth: 26
        },
        {
          name: "下一注",
          type: "bar",
          data: rows.map(function (row) {
            return Math.max(1, numOf(row.next_bet) || 1);
          }),
          itemStyle: { color: C.amber },
          barMaxWidth: 26
        },
        {
          name: "合计",
          type: "bar",
          data: rows.map(function (row) {
            return Math.max(1, numOf(row.total) || 1);
          }),
          itemStyle: { color: C.red },
          barMaxWidth: 26
        }
      ]
    });
    setChartOption("chart-m3-capital", capitalOption);
  }

  function bindModel3() {
    var handler = debounce(runModel3, 300);
    [
      "m3-base",
      "m3-mult",
      "m3-bankroll",
      "m3-rounds",
      "m3-sims",
      "m3-pwin"
    ].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
  }

  /* -------------------------------------------------------------- history */

  function historyBody() {
    var windowEl = $("h-window");
    var raw = windowEl ? windowEl.value : "all";
    return {
      window: raw === "all" ? null : Number(raw),
      periods: Math.round(
        Math.min(1000, Math.max(100, readNumber("h-periods", 300)))
      )
    };
  }

  async function runHistory() {
    var token = ++seq.history;
    setComputeState("h-state", "检验运行中…", "busy");
    try {
      var data = await postJSON("/api/history/test", historyBody(), 30000);
      if (token !== seq.history) return;
      state.history = data;
      state.computed.history = true;
      renderHistory(data);
      clearAlert("history");
      setComputeState("h-state", "已更新 " + stamp(), "ok");
    } catch (error) {
      if (token !== seq.history) return;
      if (error.status === 503) {
        setComputeState("h-state", "模型模块加载中", "busy");
        setAlert(
          "history",
          "loading",
          "模型模块加载中：后端历史检验模块尚未就绪。稍后重试，页面其他部分仍可浏览。",
          runHistory
        );
      } else {
        setComputeState("h-state", "检验失败", "error");
        setAlert("history", "error", errorMessage(error), runHistory);
      }
    }
  }

  function fmtPValue(value) {
    var p = toNum(value);
    if (p === null) return "—";
    if (p === 0) return "< 0.0001";
    if (p < 0.0001) return fmtSci(p, 2);
    return trimFixed(p, 4);
  }

  function chiConclusionData(chi) {
    var p = numOf(chi && chi.p_value);
    var conclusion = chi && chi.conclusion ? String(chi.conclusion) : null;
    var reject;
    if (p !== null) {
      reject = p < 0.05;
    } else if (conclusion) {
      reject =
        conclusion.indexOf("不拒绝") === -1 && conclusion.indexOf("拒绝") !== -1;
    } else {
      reject = false;
    }
    return { conclusion: conclusion, reject: reject };
  }

  function renderChi(prefix, chi) {
    chi = chi || {};
    var stat = numOf(chi.stat, chi.statistic, chi.chi_square);
    var df = numOf(chi.df, chi.degrees_of_freedom);
    var p = numOf(chi.p_value, chi.p);
    var critical = numOf(chi.critical_0_05, chi.critical);
    setText(prefix + "-stat", stat === null ? "—" : trimFixed(stat, 2));
    setText(prefix + "-df", df === null ? "—" : fmtInt(df));
    setText(prefix + "-p", fmtPValue(p));
    setText(prefix + "-critical", critical === null ? "—" : trimFixed(critical, 2));

    var info = chiConclusionData(chi);
    var badge = $(prefix + "-badge");
    var conclusionEl = $(prefix + "-conclusion");
    if (badge) {
      badge.textContent = info.reject ? "拒绝均匀" : "不拒绝均匀";
      badge.className = "badge " + (info.reject ? "badge--red" : "badge--teal");
    }
    if (conclusionEl) {
      conclusionEl.classList.toggle("is-reject", info.reject);
      clearNode(conclusionEl);
      var strong = document.createElement("strong");
      strong.textContent = info.reject ? "结论：分布显著偏离均匀。" : "结论：未偏离均匀。";
      conclusionEl.appendChild(strong);
      var detail;
      if (info.conclusion) {
        detail = " " + info.conclusion;
      } else if (info.reject) {
        detail =
          " 全样本频次显著偏离均匀，但异常主要集中在早期年份；把窗口缩短到最近 1000/500/300 期重做检验均不拒绝均匀，说明这是事后可见的历史波动，不能外推为预测能力。";
      } else {
        detail = " 出现频次与均匀期望的差异在统计误差内，不支持“号码有偏好”。";
      }
      conclusionEl.appendChild(document.createTextNode(detail));
    }
  }

  function observationNumber(item) {
    if (Array.isArray(item)) {
      var pairNumber = toNum(item[0]);
      return { number: pairNumber, count: toNum(item[1]) };
    }
    if (item && typeof item === "object") {
      var number = numOf(item.number, item.n, item.num, item.ball);
      var count = numOf(
        item.observed,
        item.count,
        item.freq,
        item.frequency,
        item.times
      );
      return { number: number, count: count, z: numOf(item.z, item.z_score) };
    }
    return { number: null, count: toNum(item) };
  }

  function normalizeObserved(list) {
    return asArray(list)
      .map(function (item, index) {
        var parsed = observationNumber(item);
        return {
          number: parsed.number === null ? index + 1 : parsed.number,
          count: parsed.count,
          z: parsed.z
        };
      })
      .filter(function (item) {
        return item.count !== null;
      });
  }

  function renderNumberChips(id, list, kind) {
    var container = $(id);
    if (!container) return;
    clearNode(container);
    var items = asArray(list);
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "number-chip";
      empty.textContent = "—";
      container.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var number;
      var extra = null;
      if (item && typeof item === "object" && !Array.isArray(item)) {
        number = numOf(item.number, item.n, item.num, item.ball);
        var z = numOf(item.z, item.z_score);
        var count = numOf(item.count, item.freq, item.frequency);
        if (z !== null) extra = "z " + trimFixed(z, 2);
        else if (count !== null) extra = fmtInt(count) + " 次";
      } else {
        number = toNum(Array.isArray(item) ? item[0] : item);
      }
      var chip = document.createElement("li");
      chip.className = "number-chip number-chip--" + (kind || "hot");
      chip.appendChild(document.createTextNode(number === null ? "—" : String(number).padStart(2, "0")));
      if (extra) {
        var small = document.createElement("small");
        small.textContent = extra;
        chip.appendChild(small);
      }
      container.appendChild(chip);
    });
  }

  function renderHotCold(prefix, group) {
    group = group || {};
    renderNumberChips(prefix + "-hot", group.hot, "hot");
    renderNumberChips(prefix + "-cold", group.cold, "cold");
    if (group.band_note) setText(prefix + "-note", group.band_note);
    else
      setText(
        prefix + "-note",
        "频次高低只是历史统计；超出 ±2σ 的号码需按多重比较解读（同时比较几十个号，纯随机也会有越界），把“最近常出”当成趋势是随机性错觉。"
      );
  }

  function renderHistory(data) {
    var chi = data.chi_square || {};
    renderChi("chi-front", chi.front);
    renderChi("chi-back", chi.back);

    var hot = data.hot_cold || {};
    renderHotCold("hot-front", hot.front);
    renderHotCold("hot-back", hot.back);

    var strategy = data.strategy || {};
    renderStrategyTable(strategy);
    renderHistoryCharts();

    var conclusions = asArray(data.conclusion);
    var conclusionEl = $("h-conclusion");
    if (conclusionEl) {
      conclusionEl.textContent = conclusions.length
        ? conclusions.join(" ")
        : "历史数据未显示可稳定利用的规律：冷热号、遗漏与选号策略都无法预测未来。";
    }

    renderNotes("h-limits", data.limitations, [
      "历史频次差异需结合 p 值与多重比较解读，不代表某个号码“更该出”。",
      "每期开奖相互独立，遗漏期数不会改变下一期概率。",
      "本页只做统计检验，不提供预测号码或投注建议。"
    ]);

    var strategyBadge = $("strategy-badge");
    if (strategyBadge) {
      var periods = numOf(strategy.periods);
      strategyBadge.textContent =
        periods === null ? "滚动对照" : "最近 " + fmtInt(periods) + " 期";
    }
  }

  function strategyMetrics(item) {
    if (!item || typeof item !== "object") {
      return { name: String(item || "—"), front: null, back: null, any: null, periods: null };
    }
    return {
      name: String(
        pick(item, ["name", "label", "strategy", "title"], "—")
      ),
      front: numOf(
        item.avg_front,
        item.front_hits,
        item.front_hit,
        item.front_avg,
        item.front,
        item.front_mean
      ),
      back: numOf(
        item.avg_back,
        item.back_hits,
        item.back_hit,
        item.back_avg,
        item.back,
        item.back_mean
      ),
      any: numOf(
        item.any_prize_rate,
        item.any_rate,
        item.win_rate,
        item.prize_rate,
        item.any
      ),
      periods: numOf(
        item.periods,
        item.samples,
        item.sample,
        item.sample_size,
        item.n
      ),
      verdict: item.verdict ? String(item.verdict) : null,
      se: numOf(item.front_se, item.standard_error),
      seBack: numOf(item.back_se),
      seAny: numOf(item.any_se),
      samples: numOf(item.samples)
    };
  }

  function appendStrategyRow(body, metrics, isBaseline) {
    var row = document.createElement("tr");
    if (isBaseline) row.style.color = C.muted;
    var cells = [
      metrics.name,
      metrics.front === null ? "—" : trimFixed(metrics.front, 3),
      metrics.back === null ? "—" : trimFixed(metrics.back, 3),
      metrics.any === null ? "—" : fmtPct(metrics.any, 2),
      metrics.periods === null ? "—" : fmtInt(metrics.periods)
    ];
    cells.forEach(function (text, index) {
      var td = document.createElement("td");
      if (index > 0 && index < 5) td.className = "num";
      if (index === 0) td.className = "tier-name";
      td.textContent = text;
      row.appendChild(td);
    });
    var verdictCell = document.createElement("td");
    var verdict = isBaseline ? "基准" : metrics.verdict || "—";
    verdictCell.textContent = verdict;
    if (!isBaseline) {
      verdictCell.className =
        verdict.indexOf("偏离") === 0 ? "verdict-cell is-warn" : "verdict-cell";
    }
    row.appendChild(verdictCell);
    body.appendChild(row);
  }

  function renderStrategyTable(strategy) {
    var body = $("strategy-body");
    if (!body) return;
    clearNode(body);
    var strategies = asArray(strategy.strategies);
    var baselineRaw = strategy.baseline;
    var baseline = null;
    if (baselineRaw && typeof baselineRaw === "object" && !Array.isArray(baselineRaw)) {
      baseline = strategyMetrics(
        Object.assign({ name: "理论基线" }, baselineRaw)
      );
    } else if (baselineRaw !== undefined && baselineRaw !== null) {
      baseline = {
        name: "理论基线",
        front: toNum(baselineRaw),
        back: null,
        any: null,
        periods: null
      };
    }

    if (!strategies.length && !baseline) {
      var emptyRow = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 6;
      cell.className = "table-empty";
      cell.textContent = "策略数据加载中或暂不可用…";
      emptyRow.appendChild(cell);
      body.appendChild(emptyRow);
      return;
    }

    if (baseline) appendStrategyRow(body, baseline, true);
    strategies.forEach(function (item) {
      appendStrategyRow(body, strategyMetrics(item), false);
    });

    if (strategy.note) setText("strategy-note", strategy.note);
    else
      setText(
        "strategy-note",
        "差异应落在标准误范围内。未发现任一策略能稳定跑赢机选基线。"
      );
    var seRef = null;
    strategies.forEach(function (item) {
      if (!seRef && item && numOf(item.front_se) !== null) seRef = item;
    });
    if (seRef) {
      var current = $("strategy-note");
      if (current) {
        current.textContent +=
          "（" +
          (seRef.samples ? fmtInt(seRef.samples) + " 注样本" : "样本") +
          "标准误：前区 ±" +
          trimFixed(seRef.front_se, 3) +
          "、后区 ±" +
          trimFixed(seRef.back_se, 3) +
          "、中奖率 ±" +
          fmtPct(seRef.any_se, 2) +
          "）";
      }
    }
  }

  function normalizeOmission(group) {
    var expected = numOf(group && group.expected_gap);
    var items = asArray(group && group.numbers)
      .map(function (item, index) {
        if (item && typeof item === "object") {
          return {
            number: numOf(item.number, item.n, item.num, item.ball) || index + 1,
            current: numOf(
              item.current,
              item.current_gap,
              item.gap,
              item.omission,
              item.missing
            ),
            average: numOf(item.average, item.avg, item.mean),
            max: numOf(item.max, item.max_gap)
          };
        }
        return {
          number: index + 1,
          current: toNum(item),
          average: null,
          max: null
        };
      })
      .filter(function (item) {
        return item.current !== null;
      });
    return { expected: expected, items: items };
  }

  function renderFreqChart() {
    if (!state.history) return;
    var group = (state.history.chi_square || {})[state.freqView] || {};
    var observed = normalizeObserved(group.observed);
    var expected = numOf(group.expected);
    var sigma = numOf(group.sigma);
    var numbers = observed.map(function (item) {
      return String(item.number).padStart(2, "0");
    });
    var counts = observed.map(function (item) {
      return item.count;
    });

    if (!observed.length) {
      setChartOption("chart-h-freq", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "等待频次数据…", fill: C.muted2, fontSize: 12 }
        }
      });
      return;
    }

    var upper = [];
    var lower = [];
    var meanLine = [];
    if (expected !== null && sigma !== null) {
      observed.forEach(function () {
        upper.push(expected + 2 * sigma);
        lower.push(expected - 2 * sigma);
        meanLine.push(expected);
      });
    }

    var series = [
      {
        name: "观测频次",
        type: "bar",
        data: counts,
        barMaxWidth: 18,
        itemStyle: {
          color: function (params) {
            if (!upper.length) return C.teal;
            return counts[params.dataIndex] > upper[params.dataIndex] ||
              counts[params.dataIndex] < lower[params.dataIndex]
              ? C.amber
              : C.teal;
          }
        }
      }
    ];
    if (upper.length) {
      series.push(
        {
          name: "+2σ",
          type: "line",
          data: upper,
          showSymbol: false,
          lineStyle: { color: "rgba(242,234,217,0.5)", type: "dashed", width: 1 }
        },
        {
          name: "−2σ",
          type: "line",
          data: lower,
          showSymbol: false,
          lineStyle: { color: "rgba(242,234,217,0.5)", type: "dashed", width: 1 }
        },
        {
          name: "理论均值",
          type: "line",
          data: meanLine,
          showSymbol: false,
          lineStyle: { color: C.amber, width: 1.2, type: "dotted" }
        }
      );
    }

    var option = baseOption({
      grid: { left: 46, right: 18, top: 38, bottom: 34, containLabel: true },
      legend: { top: 0, right: 0, left: "auto", itemWidth: 12 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var index = params[0].dataIndex;
          var lines = ["号码 " + numbers[index]];
          params.forEach(function (item) {
            if (item.seriesName === "观测频次") {
              lines.push(item.marker + "出现 " + fmtInt(item.value) + " 次");
            } else if (item.seriesName === "理论均值") {
              lines.push(item.marker + "理论均值 " + trimFixed(item.value, 1));
            } else if (item.seriesName === "+2σ" || item.seriesName === "−2σ") {
              lines.push(item.marker + item.seriesName + " " + trimFixed(item.value, 1));
            }
          });
          return lines.join("<br>");
        }
      },
      xAxis: {
        type: "category",
        data: numbers,
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.muted2, fontSize: 8, interval: 0 }
      },
      yAxis: Object.assign(
        {
          type: "value",
          name: "出现次数",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: { color: C.muted2, fontSize: 9 }
        },
        axisStyle()
      ),
      series: series
    });
    setChartOption("chart-h-freq", option);

    if (expected !== null && sigma !== null) {
      setText(
        "freq-caption",
        "理论均值 " +
          trimFixed(expected, 1) +
          "，±2σ 区间约 [" +
          trimFixed(expected - 2 * sigma, 1) +
          ", " +
          trimFixed(expected + 2 * sigma, 1) +
          "]。落在带外的柱子属于事后波动（多重比较下纯随机也常有越界），不构成下一期的信号。"
      );
    }
  }

  function renderOmitChart() {
    if (!state.history) return;
    var group = (state.history.omission || {})[state.omitView] || {};
    var normalized = normalizeOmission(group);
    var numbers = normalized.items.map(function (item) {
      return String(item.number).padStart(2, "0");
    });
    var values = normalized.items.map(function (item) {
      return item.current;
    });

    if (!normalized.items.length) {
      setChartOption("chart-h-omit", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "等待遗漏数据…", fill: C.muted2, fontSize: 12 }
        }
      });
      return;
    }

    var series = [
      {
        name: "当前遗漏",
        type: "bar",
        data: values,
        barMaxWidth: 18,
        itemStyle: {
          color: function (params) {
            var expected = normalized.expected;
            return expected !== null && params.value > expected * 2
              ? C.amber
              : C.teal;
          }
        }
      }
    ];
    if (normalized.expected !== null) {
      series[0].markLine = {
        silent: true,
        symbol: ["none", "none"],
        lineStyle: { color: C.red, type: "dashed", width: 1 },
        label: {
          formatter: "理论均值 " + trimFixed(normalized.expected, 1) + " 期",
          color: C.red,
          fontSize: 9,
          position: "insideEndTop"
        },
        data: [{ yAxis: normalized.expected }]
      };
    }

    var option = baseOption({
      grid: { left: 46, right: 18, top: 26, bottom: 34, containLabel: true },
      legend: { show: false },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var index = params[0].dataIndex;
          var item = normalized.items[index];
          var lines = [
            "号码 " + numbers[index],
            "当前遗漏 " + fmtInt(item.current) + " 期"
          ];
          if (item.average !== null) lines.push("历史平均 " + trimFixed(item.average, 1) + " 期");
          if (item.max !== null) lines.push("历史最大 " + fmtInt(item.max) + " 期");
          return lines.join("<br>");
        }
      },
      xAxis: {
        type: "category",
        data: numbers,
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.muted2, fontSize: 8, interval: 0 }
      },
      yAxis: Object.assign(
        {
          type: "value",
          name: "遗漏期数",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: { color: C.muted2, fontSize: 9 }
        },
        axisStyle()
      ),
      series: series
    });
    setChartOption("chart-h-omit", option);

    setText(
      "omit-caption",
      group.note ||
        "当前遗漏高于理论均值，不代表“快出了”。几何分布无记忆性，下一期每个号码的概率不变。"
    );
  }

  function renderStrategyChart() {
    if (!state.history) return;
    var strategy = state.history.strategy || {};
    var strategies = asArray(strategy.strategies).map(strategyMetrics);
    var baseline = strategyMetrics(
      Object.assign({ name: "基线" }, strategy.baseline || {})
    );
    var useAny = strategies.some(function (item) {
      return item.any !== null;
    });
    var values = strategies.map(function (item) {
      return useAny ? item.any : item.front;
    });
    var names = strategies.map(function (item) {
      return item.name;
    });
    var baselineValue = useAny ? baseline.any : baseline.front;

    if (!strategies.length) {
      setChartOption("chart-h-strategy", {
        backgroundColor: "transparent",
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: { text: "等待策略对照数据…", fill: C.muted2, fontSize: 12 }
        }
      });
      return;
    }

    var option = baseOption({
      grid: { left: 48, right: 18, top: 30, bottom: 38, containLabel: true },
      legend: { show: false },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "rgba(8,13,22,0.96)",
        borderColor: "rgba(242,234,217,0.22)",
        textStyle: { color: C.cream, fontSize: 11 },
        formatter: function (params) {
          if (!params || !params.length) return "";
          var index = params[0].dataIndex;
          var item = params[0];
          var text =
            names[index] +
            "：" +
            (useAny ? fmtPct(item.value, 3) : trimFixed(item.value, 3));
          if (baselineValue !== null) {
            text +=
              "<br>基线：" +
              (useAny ? fmtPct(baselineValue, 3) : trimFixed(baselineValue, 3));
          }
          return text;
        }
      },
      xAxis: {
        type: "category",
        data: names,
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: { color: C.muted, fontSize: 10, interval: 0 }
      },
      yAxis: Object.assign(
        {
          type: "value",
          name: useAny ? "任意奖级中奖率" : "平均前区命中",
          nameTextStyle: { color: C.muted2, fontSize: 9 },
          axisLabel: {
            color: C.muted2,
            fontSize: 9,
            formatter: function (value) {
              return useAny ? trimFixed(value * 100, 1) + "%" : trimFixed(value, 2);
            }
          }
        },
        axisStyle()
      ),
      series: [
        {
          name: "策略",
          type: "bar",
          data: values,
          barMaxWidth: 42,
          itemStyle: { color: C.teal },
          label: {
            show: true,
            position: "top",
            color: C.amber,
            fontSize: 9,
            formatter: function (params) {
              return useAny ? fmtPct(params.value, 2) : trimFixed(params.value, 2);
            }
          },
          markLine:
            baselineValue === null
              ? undefined
              : {
                  silent: true,
                  symbol: ["none", "none"],
                  lineStyle: { color: C.red, type: "dashed", width: 1 },
                  label: {
                    formatter: useAny
                      ? "基线 " + fmtPct(baselineValue, 2)
                      : "基线 " + trimFixed(baselineValue, 3),
                    color: C.red,
                    fontSize: 9,
                    position: "insideEndTop"
                  },
                  data: [{ yAxis: baselineValue }]
                }
        }
      ]
    });
    setChartOption("chart-h-strategy", option);
  }

  function renderHistoryCharts() {
    renderFreqChart();
    renderOmitChart();
    renderStrategyChart();
  }

  function bindHistory() {
    var handler = debounce(runHistory, 300);
    ["h-window", "h-periods"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
    var run = $("h-run");
    if (run) run.addEventListener("click", runHistory);

    document.querySelectorAll("[data-freq-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.freqView = button.getAttribute("data-freq-view");
        document.querySelectorAll("[data-freq-view]").forEach(function (item) {
          var active = item === button;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderFreqChart();
      });
    });

    document.querySelectorAll("[data-omit-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.omitView = button.getAttribute("data-omit-view");
        document.querySelectorAll("[data-omit-view]").forEach(function (item) {
          var active = item === button;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderOmitChart();
      });
    });
  }

  /* ---------------------------------------------------------------- init */

  function init() {
    bindNav();
    bindModel1();
    bindModel2();
    bindModel3();
    bindHistory();
    bindBudget();

    var refresh = $("refresh-btn");
    if (refresh) refresh.addEventListener("click", refreshData);

    window.addEventListener("resize", debounce(resizeCharts, 150));

    var initial = String(location.hash || "")
      .replace(/^#/, "")
      .trim();
    var deepLinked = SECTIONS.indexOf(initial) >= 0 && initial !== "overview";
    if (SECTIONS.indexOf(initial) < 0) initial = "overview";
    activate(initial, { scroll: false });
    if (!deepLinked) window.scrollTo({ top: 0, behavior: "auto" });
    loadOverview();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
