/* 预算与支出页：月度预算、支出录入、分游戏汇总与超支提示（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("budget");

  var budgetForm = document.getElementById("budget-form");
  var budgetInput = document.getElementById("monthly-budget");
  var budgetSave = document.getElementById("budget-save");
  var budgetError = document.getElementById("budget-error");
  var budgetUpdated = document.getElementById("budget-updated");

  var expenseForm = document.getElementById("expense-form");
  var expenseGame = document.getElementById("expense-game");
  var expenseAmount = document.getElementById("expense-amount");
  var expenseDate = document.getElementById("expense-date");
  var expenseNote = document.getElementById("expense-note");
  var expenseSave = document.getElementById("expense-save");
  var expenseError = document.getElementById("expense-error");

  var summaryMonth = document.getElementById("summary-month");
  var summaryCaption = document.getElementById("summary-caption");
  var summaryError = document.getElementById("summary-error");
  var summaryRoot = document.getElementById("summary-root");
  var listError = document.getElementById("list-error");
  var expensesRoot = document.getElementById("expenses-root");

  var games = [];
  var gamesPromise = null;

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function todayLocal() {
    var now = new Date();
    return now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  }

  function currentMonth() {
    return todayLocal().slice(0, 7);
  }

  function showError(box, message) {
    box.textContent = message;
    box.hidden = false;
  }

  function hideError(box) {
    box.hidden = true;
    box.textContent = "";
  }

  function fillGameSelect() {
    expenseGame.innerHTML = games
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

    var preset = "";
    try {
      preset = new URLSearchParams(window.location.search).get("game") || "";
    } catch (err) {
      preset = "";
    }
    if (
      preset &&
      games.some(function (game) {
        return game.code === preset;
      })
    ) {
      expenseGame.value = preset;
    }
  }

  function loadGames() {
    if (gamesPromise) return gamesPromise;
    gamesPromise = api("/api/helper/games")
      .then(function (data) {
        games = [];
        ((data && data.groups) || []).forEach(function (group) {
          (group.games || []).forEach(function (game) {
            games.push({
              code: game.code,
              name: game.name,
              category_label: group.category_label || game.category_label || ""
            });
          });
        });
        fillGameSelect();
        return games;
      })
      .catch(function (err) {
        gamesPromise = null;
        showError(expenseError, err.message || "加载游戏目录失败，请刷新重试");
        return [];
      });
    return gamesPromise;
  }

  function loadBudget() {
    return api("/api/helper/budget")
      .then(function (data) {
        budgetInput.value = Number(data.monthly_budget) ? data.monthly_budget : 0;
        budgetUpdated.textContent = data.updated_at
          ? "上次更新：" + fmtDate(data.updated_at)
          : "尚未设置预算";
      })
      .catch(function (err) {
        showError(budgetError, err.message || "加载预算失败，请稍后重试");
      });
  }

  function summaryHtml(data) {
    var budget = Number(data.monthly_budget) || 0;
    var spent = Number(data.total_spent) || 0;
    var remaining = Number(data.remaining) || 0;
    var percent = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;
    var danger = Boolean(data.over_budget);

    var overNotice = danger
      ? '<div class="notice notice-danger" style="margin:14px 0 0;">' +
        "本月支出已达到或超过预算，建议暂停购彩，理性对待。</div>"
      : "";

    var byGame = data.by_game || [];
    var byGameHtml = byGame.length
      ? '<div class="list">' +
        byGame
          .map(function (item) {
            return (
              '<div class="list-item">' +
              '<div class="item-head">' +
              '<div><h3 class="item-title">' +
              escapeHtml(item.game_name) +
              "</h3>" +
              '<p class="item-sub">' +
              escapeHtml(item.game_code) +
              " · " +
              item.count +
              " 笔</p></div>" +
              '<strong class="stat-value tiny">' +
              escapeHtml(fmtMoney(item.amount)) +
              "</strong>" +
              "</div>" +
              "</div>"
            );
          })
          .join("") +
        "</div>"
      : '<div class="empty">本月还没有支出记录。录入支出后会在这里按游戏汇总。</div>';

    return (
      '<div class="stat-grid">' +
      '<div class="stat"><p class="stat-label">月度预算</p><p class="stat-value">' +
      escapeHtml(fmtMoney(budget)) +
      "</p></div>" +
      '<div class="stat"><p class="stat-label">本月支出</p><p class="stat-value">' +
      escapeHtml(fmtMoney(spent)) +
      "</p></div>" +
      '<div class="stat"><p class="stat-label">剩余额度</p><p class="stat-value' +
      (danger || remaining < 0 ? " danger" : "") +
      '">' +
      escapeHtml(fmtMoney(remaining)) +
      "</p></div>" +
      '<div class="stat"><p class="stat-label">支出笔数</p><p class="stat-value">' +
      (Number(data.entry_count) || 0) +
      "</p></div>" +
      "</div>" +
      '<div class="progress-track"><div class="progress-bar' +
      (danger ? " danger" : "") +
      '" style="width:' +
      percent.toFixed(1) +
      '%"></div></div>' +
      overNotice +
      '<h3 class="section-title" style="margin:18px 0 10px;">分游戏汇总</h3>' +
      byGameHtml
    );
  }

  function loadSummary() {
    var month = summaryMonth.value || currentMonth();
    hideError(summaryError);
    summaryRoot.innerHTML = '<div class="empty">正在加载预算汇总…</div>';
    summaryCaption.textContent = "统计月份：" + month;

    return api("/api/helper/budget/summary?month=" + encodeURIComponent(month))
      .then(function (data) {
        summaryRoot.innerHTML = summaryHtml(data);
      })
      .catch(function (err) {
        summaryRoot.innerHTML = '<div class="empty">预算汇总加载失败。</div>';
        showError(summaryError, err.message || "加载预算汇总失败，请稍后重试");
      });
  }

  function expenseHtml(item) {
    return (
      '<article class="list-item" data-id="' +
      item.id +
      '">' +
      '<div class="item-head">' +
      "<div>" +
      '<h3 class="item-title">' +
      escapeHtml(item.game_name) +
      " · " +
      escapeHtml(fmtMoney(item.amount)) +
      "</h3>" +
      '<p class="item-sub">' +
      escapeHtml(item.spent_on) +
      " · " +
      escapeHtml(item.game_code) +
      "</p>" +
      (item.note ? '<p class="item-sub">备注：' + escapeHtml(item.note) + "</p>" : "") +
      "</div>" +
      '<div class="row-actions">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-action="delete">删除</button>' +
      "</div>" +
      "</div>" +
      "</article>"
    );
  }

  function loadExpenses() {
    var month = summaryMonth.value || currentMonth();
    hideError(listError);
    expensesRoot.innerHTML = '<div class="empty">正在加载支出记录…</div>';

    return api("/api/helper/expenses?month=" + encodeURIComponent(month))
      .then(function (data) {
        var items = (data && data.items) || [];
        if (!items.length) {
          expensesRoot.innerHTML =
            '<div class="empty">本月还没有支出记录。按实际购彩金额手动记录即可。</div>';
          return;
        }
        expensesRoot.innerHTML =
          '<div class="list">' + items.map(expenseHtml).join("") + "</div>";
      })
      .catch(function (err) {
        expensesRoot.innerHTML = '<div class="empty">支出记录加载失败。</div>';
        showError(listError, err.message || "加载支出记录失败，请稍后重试");
      });
  }

  function refreshMonth() {
    loadSummary();
    loadExpenses();
  }

  budgetForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError(budgetError);

    var raw = budgetInput.value.trim();
    var value = Number(raw);
    if (raw === "" || !isFinite(value) || value < 0 || value > 1000000) {
      showError(budgetError, "请输入 0–1,000,000 之间的预算金额");
      return;
    }

    budgetSave.disabled = true;
    api("/api/helper/budget", {
      method: "PUT",
      body: JSON.stringify({ monthly_budget: value })
    })
      .then(function (data) {
        budgetInput.value = data.monthly_budget;
        budgetUpdated.textContent = "上次更新：" + fmtDate(data.updated_at);
        loadSummary();
      })
      .catch(function (err) {
        showError(budgetError, err.message || "保存预算失败，请稍后重试");
      })
      .finally(function () {
        budgetSave.disabled = false;
      });
  });

  expenseForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError(expenseError);

    if (!expenseGame.value) {
      showError(expenseError, "请选择游戏");
      return;
    }
    var amount = Number(expenseAmount.value);
    if (!isFinite(amount) || amount <= 0 || amount > 100000) {
      showError(expenseError, "金额需大于 0 且不超过 100,000 元");
      return;
    }
    var spentOn = expenseDate.value;
    if (!spentOn) {
      showError(expenseError, "请选择支出日期");
      return;
    }
    if (spentOn > todayLocal()) {
      showError(expenseError, "支出日期不能晚于今天");
      return;
    }
    if (expenseNote.value.length > 200) {
      showError(expenseError, "备注最多 200 字");
      return;
    }

    expenseSave.disabled = true;
    api("/api/helper/expenses", {
      method: "POST",
      body: JSON.stringify({
        game_code: expenseGame.value,
        amount: amount,
        spent_on: spentOn,
        note: expenseNote.value.trim()
      })
    })
      .then(function (item) {
        expenseAmount.value = "";
        expenseNote.value = "";
        if (summaryMonth.value !== item.spent_on.slice(0, 7)) {
          summaryMonth.value = item.spent_on.slice(0, 7);
        }
        refreshMonth();
      })
      .catch(function (err) {
        showError(expenseError, err.message || "记录支出失败，请稍后重试");
      })
      .finally(function () {
        expenseSave.disabled = false;
      });
  });

  expensesRoot.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action='delete']");
    if (!button) return;
    var card = button.closest("[data-id]");
    if (!card) return;
    var id = Number(card.getAttribute("data-id"));
    if (!window.confirm("确认删除这条支出记录？")) return;

    button.disabled = true;
    api("/api/helper/expenses/" + id, { method: "DELETE" })
      .then(refreshMonth)
      .catch(function (err) {
        button.disabled = false;
        showError(listError, err.message || "删除失败，请稍后重试");
      });
  });

  summaryMonth.addEventListener("change", refreshMonth);

  summaryMonth.value = currentMonth();
  expenseDate.value = todayLocal();

  loadGames();
  loadBudget();
  refreshMonth();
})();
