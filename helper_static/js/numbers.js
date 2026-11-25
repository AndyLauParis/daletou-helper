/* 号码本页：按游戏筛选、新增/编辑/删除号码记录（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("numbers");

  var PAGE_SIZE = 50;

  var form = document.getElementById("record-form");
  var formTitle = document.getElementById("form-title");
  var gameSelect = document.getElementById("game-code");
  var nameInput = document.getElementById("record-name");
  var playTypeInput = document.getElementById("play-type");
  var payloadInput = document.getElementById("payload");
  var formError = document.getElementById("form-error");
  var formWarning = document.getElementById("form-warning");
  var saveBtn = document.getElementById("save-btn");
  var cancelBtn = document.getElementById("cancel-btn");
  var filterSelect = document.getElementById("filter-game");
  var categoryFilter = document.getElementById("filter-category");
  var daysFilter = document.getElementById("filter-days");
  var listCount = document.getElementById("list-count");
  var listError = document.getElementById("list-error");
  var recordsRoot = document.getElementById("records-root");
  var moreWrap = document.getElementById("more-wrap");
  var moreBtn = document.getElementById("more-btn");

  var games = [];
  var groups = [];
  var records = [];
  var total = 0;
  var editingId = null;
  var gamesPromise = null;

  function showError(box, message) {
    box.textContent = message;
    box.hidden = false;
  }

  function hideError(box) {
    box.hidden = true;
    box.textContent = "";
  }

  function showWarning(message) {
    if (!message) {
      formWarning.hidden = true;
      formWarning.textContent = "";
      return;
    }
    formWarning.textContent = message;
    formWarning.hidden = false;
  }

  function fillGameSelects() {
    var options = games
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
    gameSelect.innerHTML = options;
    filterSelect.innerHTML = '<option value="">全部游戏</option>' + options;
    fillCategorySelect();
  }

  function fillCategorySelect() {
    var options = groups
      .map(function (group) {
        return (
          '<option value="' +
          escapeHtml(group.category) +
          '">' +
          escapeHtml(group.category_label) +
          "</option>"
        );
      })
      .join("");
    categoryFilter.innerHTML = '<option value="">全部类别</option>' + options;
  }

  function gameCategory(code) {
    for (var i = 0; i < games.length; i += 1) {
      if (games[i].code === code) return games[i].category || "";
    }
    return "";
  }

  function loadGames() {
    if (gamesPromise) return gamesPromise;
    gamesPromise = api("/api/helper/games")
      .then(function (data) {
        games = [];
        groups = (data && data.groups) || [];
        groups.forEach(function (group) {
          (group.games || []).forEach(function (game) {
            games.push({
              code: game.code,
              name: game.name,
              category: group.category || "",
              category_label: group.category_label || game.category_label || ""
            });
          });
        });
        fillGameSelects();
        return games;
      })
      .catch(function (err) {
        gamesPromise = null;
        showError(listError, err.message || "加载游戏目录失败，请刷新重试");
        return [];
      });
    return gamesPromise;
  }

  function payloadToText(payload) {
    if (
      payload &&
      typeof payload === "object" &&
      !Array.isArray(payload) &&
      Object.keys(payload).length === 1 &&
      typeof payload.text === "string"
    ) {
      return payload.text;
    }
    return JSON.stringify(payload || {}, null, 2);
  }

  function parsePayload(text) {
    var raw = (text || "").trim();
    if (!raw) throw new Error("请输入号码内容");
    if (raw.charAt(0) === "{" || raw.charAt(0) === "[") {
      var parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (err) {
        throw new Error("JSON 格式有误，请检查括号、引号与逗号");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("号码内容需为 JSON 对象或纯文本");
      }
      return parsed;
    }
    return { text: raw };
  }

  function recordHtml(record) {
    var title = record.name ? escapeHtml(record.name) : "未命名记录";
    var sub = escapeHtml(record.game_name) + " · " + escapeHtml(record.game_code);
    if (record.play_type) sub += " · " + escapeHtml(record.play_type);
    return (
      '<article class="list-item" data-id="' +
      record.id +
      '">' +
      '<div class="item-head">' +
      "<div>" +
      '<h3 class="item-title">' +
      title +
      "</h3>" +
      '<p class="item-sub">' +
      sub +
      "</p>" +
      "</div>" +
      '<div class="row-actions">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-action="edit">编辑</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-action="delete">删除</button>' +
      "</div>" +
      "</div>" +
      '<pre class="payload">' +
      escapeHtml(payloadToText(record.payload)) +
      "</pre>" +
      '<p class="item-meta">更新于 ' +
      escapeHtml(fmtDate(record.updated_at)) +
      "</p>" +
      "</article>"
    );
  }

  function hasFilters() {
    return Boolean(filterSelect.value || categoryFilter.value || daysFilter.value);
  }

  function renderRecords() {
    listCount.textContent = "共 " + total + " 条记录" + (records.length < total ? "（已显示 " + records.length + " 条）" : "");
    if (!records.length) {
      recordsRoot.innerHTML =
        '<div class="empty">' +
        (hasFilters()
          ? "没有符合筛选条件的记录。"
          : "还没有号码记录。选择游戏并保存你的第一组号码吧。") +
        "</div>";
      moreWrap.hidden = true;
      return;
    }
    recordsRoot.innerHTML =
      '<div class="list">' + records.map(recordHtml).join("") + "</div>";
    moreWrap.hidden = records.length >= total;
  }

  function loadRecords(reset) {
    if (reset) {
      records = [];
      total = 0;
      recordsRoot.innerHTML = '<div class="empty">正在加载号码记录…</div>';
    }
    hideError(listError);

    var params = new URLSearchParams();
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(records.length));
    if (filterSelect.value) params.set("game_code", filterSelect.value);
    if (categoryFilter.value) params.set("category", categoryFilter.value);
    if (daysFilter.value) params.set("days", daysFilter.value);

    return api("/api/helper/numbers?" + params.toString())
      .then(function (data) {
        total = Number(data.total) || 0;
        records = records.concat(data.items || []);
        renderRecords();
      })
      .catch(function (err) {
        if (reset) {
          recordsRoot.innerHTML = '<div class="empty">号码记录加载失败。</div>';
        }
        showError(listError, err.message || "加载号码记录失败，请稍后重试");
        moreWrap.hidden = true;
      });
  }

  function resetForm() {
    editingId = null;
    formTitle.textContent = "新增记录";
    saveBtn.textContent = "保存记录";
    cancelBtn.hidden = true;
    nameInput.value = "";
    playTypeInput.value = "";
    payloadInput.value = "";
    hideError(formError);
    showWarning("");
  }

  function startEdit(record) {
    editingId = record.id;
    formTitle.textContent = "编辑记录";
    saveBtn.textContent = "保存修改";
    cancelBtn.hidden = false;
    gameSelect.value = record.game_code;
    gameSelect.disabled = true;
    nameInput.value = record.name || "";
    playTypeInput.value = record.play_type || "";
    payloadInput.value = payloadToText(record.payload);
    hideError(formError);
    showWarning("");
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function findRecord(id) {
    for (var i = 0; i < records.length; i += 1) {
      if (records[i].id === id) return records[i];
    }
    return null;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError(formError);
    showWarning("");

    if (!gameSelect.value) {
      showError(formError, "请选择游戏");
      return;
    }

    var payload;
    try {
      payload = parsePayload(payloadInput.value);
    } catch (err) {
      showError(formError, err.message);
      return;
    }

    var body = {
      game_code: gameSelect.value,
      name: nameInput.value.trim(),
      play_type: playTypeInput.value.trim() || null,
      payload: payload
    };

    saveBtn.disabled = true;
    var request = editingId
      ? api("/api/helper/numbers/" + editingId, {
          method: "PUT",
          body: JSON.stringify(body)
        })
      : api("/api/helper/numbers", {
          method: "POST",
          body: JSON.stringify(body)
        });

    request
      .then(function (data) {
        if (data && data.warning) {
          showWarning("已保存，格式提示：" + data.warning);
        }
        resetForm();
        gameSelect.disabled = false;
        loadRecords(true);
      })
      .catch(function (err) {
        showError(formError, err.message || "保存失败，请稍后重试");
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  });

  cancelBtn.addEventListener("click", function () {
    resetForm();
    gameSelect.disabled = false;
  });

  filterSelect.addEventListener("change", function () {
    if (filterSelect.value) {
      var category = gameCategory(filterSelect.value);
      if (category) {
        categoryFilter.value = category;
        categoryFilter.disabled = true;
      }
    } else {
      categoryFilter.disabled = false;
    }
    loadRecords(true);
  });

  categoryFilter.addEventListener("change", function () {
    loadRecords(true);
  });

  daysFilter.addEventListener("change", function () {
    loadRecords(true);
  });

  moreBtn.addEventListener("click", function () {
    moreBtn.disabled = true;
    loadRecords(false).finally(function () {
      moreBtn.disabled = false;
    });
  });

  recordsRoot.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action]");
    if (!button) return;
    var card = button.closest("[data-id]");
    if (!card) return;
    var id = Number(card.getAttribute("data-id"));
    var record = findRecord(id);
    if (!record) return;

    if (button.getAttribute("data-action") === "edit") {
      startEdit(record);
      return;
    }

    if (!window.confirm("确认删除这条号码记录？删除后无法恢复。")) return;
    button.disabled = true;
    api("/api/helper/numbers/" + id, { method: "DELETE" })
      .then(function () {
        if (editingId === id) {
          resetForm();
          gameSelect.disabled = false;
        }
        loadRecords(true);
      })
      .catch(function (err) {
        button.disabled = false;
        showError(listError, err.message || "删除失败，请稍后重试");
      });
  });

  loadGames().then(function () {
    if (games.length) loadRecords(true);
  });
})();
