/* 票据识别与号码积累（外置以支持严格 CSP：script-src 'self'） */
(function () {
  "use strict";

  mountShell("recognition");

  var PAGE_SIZE = 20;
  var MAX_IMAGE_BYTES = 8 * 1024 * 1024;

  var state = { page: 1, file: null, previewUrl: "", games: [] };

  var errorBox = document.getElementById("recognition-error");
  var resultBox = document.getElementById("recognition-result");
  var fileInput = document.getElementById("recognition-file");
  var previewBox = document.getElementById("recognition-preview");
  var previewImage = document.getElementById("recognition-image");
  var fileName = document.getElementById("recognition-name");
  var gameSelect = document.getElementById("recognition-game");
  var filterGame = document.getElementById("filter-game");
  var submitBtn = document.getElementById("recognition-submit");
  var recordsBody = document.getElementById("records-body");
  var recordsEmpty = document.getElementById("records-empty");

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
      date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) +
      " " + pad(date.getHours()) + ":" + pad(date.getMinutes())
    );
  }

  function statusBadge(status, label) {
    var cls =
      status === "valid" ? "badge badge-ok" :
      status === "review" ? "badge badge-warn" : "badge badge-muted";
    return '<span class="' + cls + '">' + escapeHtml(label) + "</span>";
  }

  function renderOcrStatus(config) {
    var notice = document.getElementById("ocr-status");
    if (!config || !config.enabled) {
      notice.className = "notice notice-danger";
      notice.textContent =
        "票面识别服务尚未配置，上传识别暂不可用。请在服务端设置 HELPER_OCR_BASE_URL、" +
        "HELPER_OCR_API_KEY 与 HELPER_OCR_MODEL（需支持图片输入）后重启服务。";
      return;
    }
    notice.className = "notice notice-info";
    notice.textContent =
      "识别服务：" + (config.provider || "视觉接口") + " · " + (config.model || "") +
      "；置信度低于 " + Math.round((config.threshold || 0) * 100) + "% 的记录会标记为待人工审核。";
  }

  function fillGames(games) {
    state.games = games || [];
    state.games.forEach(function (game) {
      var option = document.createElement("option");
      option.value = game.code;
      option.textContent = game.name;
      gameSelect.appendChild(option);
      var filterOption = document.createElement("option");
      filterOption.value = game.code;
      filterOption.textContent = game.name;
      filterGame.appendChild(filterOption);
    });
  }

  function setFile(file) {
    if (state.previewUrl) {
      URL.revokeObjectURL(state.previewUrl);
      state.previewUrl = "";
    }
    state.file = file || null;
    if (!file) {
      previewBox.hidden = true;
      fileInput.value = "";
      return;
    }
    state.previewUrl = URL.createObjectURL(file);
    previewImage.src = state.previewUrl;
    fileName.textContent = file.name + " · " + Math.round(file.size / 1024) + " KB";
    previewBox.hidden = false;
  }

  fileInput.addEventListener("change", function () {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      showError("仅支持 PNG、JPG 或 WebP 图片");
      setFile(null);
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      showError("图片不能超过 8 MB");
      setFile(null);
      return;
    }
    clearError();
    setFile(file);
  });

  document.getElementById("recognition-remove").addEventListener("click", function () {
    setFile(null);
  });

  function renderResult(data) {
    var record = data.record || {};
    document.getElementById("result-game").textContent =
      record.game_name || record.game_code || "未知类型";
    document.getElementById("result-issue").textContent = "第 " + (record.issue || "—") + " 期";
    var statusEl = document.getElementById("result-status");
    statusEl.className =
      record.status === "valid" ? "badge badge-ok" :
      record.status === "review" ? "badge badge-warn" : "badge badge-muted";
    statusEl.textContent = record.status_label || record.status || "";
    document.getElementById("result-numbers").textContent =
      record.numbers_text || JSON.stringify(record.payload || {});
    document.getElementById("result-meta").textContent =
      "总体置信度 " + Math.round((record.confidence || 0) * 100) + "%" +
      "；已自动加入积累库（后台写入，稍后可在下方查看）。";
    var reason = document.getElementById("result-reason");
    if (record.anomaly_reason) {
      reason.hidden = false;
      reason.textContent = "提示：" + record.anomaly_reason;
    } else {
      reason.hidden = true;
    }
    resultBox.hidden = false;
  }

  submitBtn.addEventListener("click", async function () {
    clearError();
    resultBox.hidden = true;
    if (!state.file) {
      showError("请先选择一张彩票照片");
      return;
    }
    var form = new FormData();
    form.append("image", state.file);
    var game = gameSelect.value;
    var issue = document.getElementById("recognition-issue").value.trim();
    if (game) form.append("game_code", game);
    if (issue) form.append("issue", issue);

    submitBtn.disabled = true;
    submitBtn.textContent = "识别中…";
    try {
      var data = await api("/api/helper/recognition/scan", {
        method: "POST",
        body: form
      });
      renderResult(data);
      showToast("识别完成，已自动积累");
      setFile(null);
      setTimeout(refreshAll, 600);
      setTimeout(refreshAll, 1800);
    } catch (err) {
      showError(err.message || "识别失败，请稍后重试");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "开始识别";
    }
  });

  function renderStats(data) {
    var byStatus = data.by_status || {};
    var games = data.by_game || [];
    var topGame = games.length ? games[0].game_name + " " + games[0].count + " 条" : "—";
    var tiles = [
      { label: "积累记录", value: data.total || 0 },
      { label: "有效", value: byStatus.valid || 0 },
      { label: "待人工审核", value: byStatus.review || 0 },
      { label: "异常", value: byStatus.anomaly || 0 },
      { label: "平均置信度", value: Math.round((data.avg_confidence || 0) * 100) + "%" },
      { label: "重复命中", value: data.duplicate_hits || 0 }
    ];
    document.getElementById("recognition-stats").innerHTML = tiles
      .map(function (tile) {
        return (
          '<div class="stat"><p class="stat-label">' + escapeHtml(tile.label) +
          '</p><p class="stat-value">' + escapeHtml(tile.value) + "</p></div>"
        );
      })
      .join("");
    document.getElementById("recognition-stats-note").textContent =
      "识别最多：" + topGame +
      (data.latest_recognized_at ? "；最近识别：" + fmtDateTime(data.latest_recognized_at) : "");
  }

  function buildQuery() {
    var params = new URLSearchParams();
    var pairs = [
      ["game_code", filterGame.value],
      ["issue", document.getElementById("filter-issue").value.trim()],
      ["status", document.getElementById("filter-status").value],
      ["date_from", document.getElementById("filter-from").value],
      ["date_to", document.getElementById("filter-to").value],
      ["keyword", document.getElementById("filter-keyword").value.trim()]
    ];
    pairs.forEach(function (pair) {
      if (pair[1]) params.set(pair[0], pair[1]);
    });
    return params;
  }

  function renderRecords(data) {
    var items = data.items || [];
    recordsBody.innerHTML = items
      .map(function (item) {
        var actions = "";
        if (item.status !== "valid") {
          actions +=
            '<button class="btn btn-ghost btn-sm" type="button" data-record-id="' +
            encodeURIComponent(item.id) + '" data-next-status="valid">确认无误</button>';
        }
        if (item.status !== "anomaly") {
          actions +=
            '<button class="btn btn-ghost btn-sm" type="button" data-record-id="' +
            encodeURIComponent(item.id) + '" data-next-status="anomaly">标记异常</button>';
        }
        var statusCell = statusBadge(item.status, item.status_label);
        if (item.anomaly_reason) {
          statusCell += '<div class="hint">' + escapeHtml(item.anomaly_reason) + "</div>";
        }
        return (
          "<tr>" +
          "<td>" + escapeHtml(item.issue) + "</td>" +
          "<td>" + escapeHtml(item.game_name) + "</td>" +
          "<td>" + escapeHtml(item.numbers_text) + "</td>" +
          "<td>" + Math.round((item.confidence || 0) * 100) + "%</td>" +
          "<td>" + statusCell + "</td>" +
          "<td>" + escapeHtml(fmtDateTime(item.recognized_at)) + "</td>" +
          "<td>" + escapeHtml(item.seen_count) + "</td>" +
          '<td><div class="row-actions">' + actions + "</div></td>" +
          "</tr>"
        );
      })
      .join("");
    recordsEmpty.hidden = items.length > 0;
    document.getElementById("records-summary").textContent =
      "共 " + (data.total || 0) + " 条记录";
    setPager(data.total || 0);
  }

  function setPager(total) {
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    document.getElementById("records-page-info").textContent =
      "第 " + state.page + " / " + pages + " 页 · 共 " + total + " 条";
    document.getElementById("records-prev").disabled = state.page <= 1;
    document.getElementById("records-next").disabled = state.page >= pages;
  }

  async function loadRecords() {
    var params = buildQuery();
    params.set("page", String(state.page));
    params.set("page_size", String(PAGE_SIZE));
    var data = await api("/api/helper/recognition/records?" + params.toString());
    renderRecords(data);
  }

  async function loadStats() {
    renderStats(await api("/api/helper/recognition/stats"));
  }

  function refreshAll() {
    return Promise.all([loadRecords(), loadStats()]).catch(function (err) {
      showError(err.message || "加载积累数据失败");
    });
  }

  recordsBody.addEventListener("click", async function (event) {
    var button =
      event.target && event.target.closest
        ? event.target.closest("[data-record-id]")
        : null;
    if (!button) return;
    button.disabled = true;
    clearError();
    try {
      await api("/api/helper/recognition/records/" + button.getAttribute("data-record-id"), {
        method: "PATCH",
        body: JSON.stringify({ status: button.getAttribute("data-next-status") })
      });
      showToast("记录状态已更新");
      await refreshAll();
    } catch (err) {
      showToast(err.message || "更新失败，请稍后重试");
      button.disabled = false;
    }
  });

  document.getElementById("filter-apply").addEventListener("click", function () {
    state.page = 1;
    loadRecords().catch(function (err) {
      showError(err.message || "加载记录失败");
    });
  });

  document.getElementById("filter-reset").addEventListener("click", function () {
    filterGame.value = "";
    document.getElementById("filter-issue").value = "";
    document.getElementById("filter-status").value = "";
    document.getElementById("filter-from").value = "";
    document.getElementById("filter-to").value = "";
    document.getElementById("filter-keyword").value = "";
    state.page = 1;
    loadRecords().catch(function (err) {
      showError(err.message || "加载记录失败");
    });
  });

  document.getElementById("stats-refresh").addEventListener("click", function () {
    loadStats().catch(function (err) {
      showError(err.message || "加载统计失败");
    });
  });

  document.getElementById("records-prev").addEventListener("click", function () {
    if (state.page <= 1) return;
    state.page -= 1;
    loadRecords().catch(function (err) {
      showError(err.message || "加载记录失败");
    });
  });

  document.getElementById("records-next").addEventListener("click", function () {
    state.page += 1;
    loadRecords().catch(function (err) {
      showError(err.message || "加载记录失败");
    });
  });

  function exportRecords(format) {
    var params = buildQuery();
    params.set("format", format);
    var link = document.createElement("a");
    link.href = "/api/helper/recognition/export?" + params.toString();
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  document.getElementById("export-csv").addEventListener("click", function () {
    exportRecords("csv");
  });

  document.getElementById("export-json").addEventListener("click", function () {
    exportRecords("json");
  });

  document.getElementById("revalidate-btn").addEventListener("click", async function () {
    var button = document.getElementById("revalidate-btn");
    button.disabled = true;
    try {
      var data = await api("/api/helper/recognition/revalidate", { method: "POST" });
      showToast("已重新校验 " + (data.checked || 0) + " 条，更新 " + (data.changed || 0) + " 条");
      await refreshAll();
    } catch (err) {
      showToast(err.message || "重新校验失败");
    } finally {
      button.disabled = false;
    }
  });

  (async function bootstrap() {
    try {
      var config = await api("/api/helper/recognition/config");
      renderOcrStatus(config);
      fillGames((config && config.supported_games) || []);
      if (config && config.max_image_bytes) {
        MAX_IMAGE_BYTES = Math.min(MAX_IMAGE_BYTES, config.max_image_bytes);
      }
    } catch (err) {
      renderOcrStatus(null);
    }
    await refreshAll();
  })();
})();
