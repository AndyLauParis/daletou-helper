/* 我的收藏：本地收藏列表的展示、移除与清空（无框架、无外部依赖） */
(function () {
  "use strict";

  mountShell("favorites");

  var listEl = document.getElementById("fav-list");
  var countEl = document.getElementById("fav-count");
  var emptyEl = document.getElementById("fav-empty");
  var clearBtn = document.getElementById("fav-clear");
  var backBtn = document.getElementById("fav-back");

  function safeHref(href) {
    var value = String(href || "");
    return value.charAt(0) === "/" ? value : "#";
  }

  function kindLabel(kind) {
    return kind === "tool" ? "工具" : "页面";
  }

  function render(items) {
    var list = Array.isArray(items) ? items : [];
    countEl.textContent = list.length ? list.length + " 项收藏" : "暂无收藏";
    clearBtn.disabled = !list.length;
    backBtn.hidden = !list.length;
    emptyEl.hidden = list.length > 0;
    listEl.innerHTML = list
      .map(function (item) {
        return (
          '<article class="fav-item">' +
          '<div class="fav-item-main">' +
          '<div class="fav-item-title">' +
          '<span class="badge badge-soft">' +
          kindLabel(item.kind) +
          "</span>" +
          "<h2>" +
          escapeHtml(item.label) +
          "</h2>" +
          "</div>" +
          '<p class="fav-item-meta">收藏于 ' +
          escapeHtml(fmtDate(item.addedAt)) +
          " · " +
          escapeHtml(item.href) +
          "</p>" +
          "</div>" +
          '<div class="row-actions">' +
          '<a class="btn btn-ghost btn-sm" href="' +
          escapeHtml(safeHref(item.href)) +
          '">打开</a>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-remove-fav="' +
          escapeHtml(item.id) +
          '">移除</button>' +
          "</div>" +
          "</article>"
        );
      })
      .join("");
  }

  listEl.addEventListener("click", function (event) {
    var button = event.target.closest
      ? event.target.closest("[data-remove-fav]")
      : null;
    if (!button) return;
    window.HelperFavorites.remove(button.getAttribute("data-remove-fav"));
    showToast("已从收藏中移除");
  });

  clearBtn.addEventListener("click", function () {
    if (!window.HelperFavorites.list().length) return;
    if (!window.confirm("清空全部收藏？此操作只影响当前浏览器。")) return;
    window.HelperFavorites.clear();
    showToast("收藏已清空");
  });

  window.HelperFavorites.subscribe(render);
})();
