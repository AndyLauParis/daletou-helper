/* 全国彩票购彩辅助工具 —— 公共前端脚本（无框架、无外部依赖） */
(function () {
  "use strict";

  /* 会话令牌由服务端 HttpOnly Cookie 保存，前端不再接触令牌。 */
  var LEGACY_TOKEN_KEY = "helper_token";
  var LOGIN_FLAG_KEY = "helper_logged_in";
  var ADMIN_FLAG_KEY = "helper_is_admin";
  var LOGIN_PAGE = "/login";

  var NAV_ITEMS = [
    { key: "home", label: "首页", href: "/", public: true },
    { key: "games", label: "游戏目录", href: "/static/games.html", public: true },
    { key: "lab", label: "数据实验室", href: "/lab", public: true },
    { key: "picker", label: "娱乐选号", href: "/picker", public: true },
    { key: "favorites", label: "我的收藏", href: "/static/favorites.html" },
    { key: "numbers", label: "号码本", href: "/static/numbers.html" },
    { key: "budget", label: "预算", href: "/static/budget.html" },
    { key: "draws", label: "开奖核对", href: "/static/draws.html" },
    { key: "reminders", label: "提醒", href: "/static/reminders.html" },
    { key: "feedback", label: "意见反馈", href: "/static/feedback.html" },
    { key: "settings", label: "设置", href: "/static/settings.html" },
    { key: "admin", label: "管理", href: "/admin", admin: true }
  ];

  var COMPLIANCE_TEXT =
    "本工具仅提供记录、查询、提醒与娱乐选号，不代购、不支付、不出票、不承诺中奖；" +
    "娱乐选号仅为号码组合规则，不构成购彩建议；" +
    "请通过官方线下渠道购彩；未成年人不得购彩。";

  function clearLegacyToken() {
    try {
      localStorage.removeItem(LEGACY_TOKEN_KEY);
    } catch (err) {
      /* ignore */
    }
  }

  function isLoggedIn() {
    try {
      return localStorage.getItem(LOGIN_FLAG_KEY) === "1";
    } catch (err) {
      return false;
    }
  }

  function setLoggedIn(value) {
    try {
      if (value) {
        localStorage.setItem(LOGIN_FLAG_KEY, "1");
      } else {
        localStorage.removeItem(LOGIN_FLAG_KEY);
        localStorage.removeItem(ADMIN_FLAG_KEY);
      }
    } catch (err) {
      /* 隐私模式下忽略写入失败 */
    }
  }

  function isAdmin() {
    try {
      return localStorage.getItem(ADMIN_FLAG_KEY) === "1";
    } catch (err) {
      return false;
    }
  }

  function setIsAdmin(value) {
    try {
      if (value) {
        localStorage.setItem(ADMIN_FLAG_KEY, "1");
      } else {
        localStorage.removeItem(ADMIN_FLAG_KEY);
      }
    } catch (err) {
      /* 隐私模式下忽略写入失败 */
    }
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtMoney(value) {
    var num = Number(value);
    if (!isFinite(num)) num = 0;
    return (
      "¥" +
      num.toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })
    );
  }

  function fmtDate(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    var pad = function (n) {
      return n < 10 ? "0" + n : String(n);
    };
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate())
    );
  }

  async function readDetail(response, fallback) {
    try {
      var data = await response.json();
      if (data && typeof data.detail === "string" && data.detail) {
        return data.detail;
      }
      if (data && typeof data.message === "string" && data.message) {
        return data.message;
      }
    } catch (err) {
      /* 非 JSON 响应 */
    }
    return fallback;
  }

  async function api(path, options) {
    var opts = Object.assign({}, options || {});
    var headers = new Headers(opts.headers || {});
    if (typeof opts.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    opts.headers = headers;
    /* 同源请求自动携带 HttpOnly Cookie 会话 */
    opts.credentials = opts.credentials || "same-origin";

    var response;
    try {
      response = await fetch(path, opts);
    } catch (err) {
      throw new Error("网络异常，请检查网络后重试");
    }

    if (response.status === 401) {
      /* redirectOn401 === false 时由调用方自行处理登录态（例如公开落地页） */
      if (!(opts && opts.redirectOn401 === false)) {
        setLoggedIn(false);
        if (
          window.location.pathname !== "/login" &&
          window.location.pathname !== "/register"
        ) {
          window.location.href = LOGIN_PAGE;
        }
      }
      throw new Error(await readDetail(response, "请先登录"));
    }

    if (!response.ok) {
      var error = new Error(
        await readDetail(response, "请求失败（" + response.status + "）")
      );
      error.status = response.status;
      throw error;
    }

    if (response.status === 204) return null;
    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") !== -1) {
      return response.json();
    }
    return response.text();
  }

  /* ------------------------------------------------------------------
     收藏：localStorage 持久化 + 同页/跨标签实时同步
     ------------------------------------------------------------------ */
  var FAVORITES_KEY = "helper_favorites_v1";
  var FAVORITES_LIMIT = 100;

  function normalizeFavorite(input) {
    var id = String((input && input.id) || "").trim();
    if (!id) return null;
    return {
      id: id.slice(0, 300),
      label: String(input.label || id).trim().slice(0, 60),
      href: String(input.href || id).trim().slice(0, 300),
      kind: input.kind === "tool" ? "tool" : "page",
      addedAt: input.addedAt || new Date().toISOString()
    };
  }

  function getFavorites() {
    try {
      var raw = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
      if (!Array.isArray(raw)) return [];
      var seen = {};
      return raw
        .map(normalizeFavorite)
        .filter(function (item) {
          if (!item || seen[item.id]) return false;
          seen[item.id] = true;
          return true;
        })
        .slice(0, FAVORITES_LIMIT);
    } catch (err) {
      return [];
    }
  }

  function emitFavorites() {
    var items = getFavorites();
    try {
      window.dispatchEvent(
        new CustomEvent("helper:favorites-changed", { detail: { items: items } })
      );
    } catch (err) {
      /* 旧浏览器不支持 CustomEvent 构造器时忽略 */
    }
  }

  function writeFavorites(items) {
    try {
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(items));
    } catch (err) {
      /* 隐私模式或存储已满：仍然触发界面刷新 */
    }
    emitFavorites();
  }

  function isFavorite(id) {
    var value = String(id || "");
    return getFavorites().some(function (item) {
      return item.id === value;
    });
  }

  function addFavorite(input) {
    var fav = normalizeFavorite(input);
    if (!fav) return getFavorites();
    var items = getFavorites().filter(function (item) {
      return item.id !== fav.id;
    });
    items.unshift(fav);
    items = items.slice(0, FAVORITES_LIMIT);
    writeFavorites(items);
    return items;
  }

  function removeFavorite(id) {
    var value = String(id || "");
    var items = getFavorites().filter(function (item) {
      return item.id !== value;
    });
    writeFavorites(items);
    return items;
  }

  function toggleFavorite(input) {
    var fav = normalizeFavorite(input);
    if (!fav) return { active: false, items: getFavorites() };
    if (isFavorite(fav.id)) {
      return { active: false, items: removeFavorite(fav.id) };
    }
    addFavorite(fav);
    return { active: true, items: getFavorites() };
  }

  function clearFavorites() {
    writeFavorites([]);
    return [];
  }

  function subscribeFavorites(listener) {
    if (typeof listener !== "function") return function () {};
    var handler = function (event) {
      listener(
        (event && event.detail && event.detail.items) || getFavorites()
      );
    };
    window.addEventListener("helper:favorites-changed", handler);
    listener(getFavorites());
    return function () {
      window.removeEventListener("helper:favorites-changed", handler);
    };
  }

  window.addEventListener("storage", function (event) {
    if (event.key === FAVORITES_KEY || event.key === null) {
      emitFavorites();
    }
  });

  /* ------------------------------------------------------------------
     主题与收藏按钮
     ------------------------------------------------------------------ */
  function starIcon() {
    return (
      '<svg class="star-icon" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">' +
      '<path d="M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" ' +
      'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>'
    );
  }

  function themeIcons() {
    return (
      '<svg class="theme-icon icon-moon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' +
      '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z" ' +
      'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>' +
      '<svg class="theme-icon icon-sun" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' +
      '<circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="1.7"/>' +
      '<path d="M12 2.4v2.2M12 19.4v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.4 12h2.2M19.4 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" ' +
      'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'
    );
  }

  function pageFavoriteMeta() {
    var path = window.location.pathname.replace(/\/+$/, "") || "/";
    if (
      path === "/login" ||
      path === "/register" ||
      path === "/admin" ||
      path === "/static/favorites.html"
    ) {
      return null;
    }
    var matched = null;
    NAV_ITEMS.forEach(function (item) {
      if (item.href === path) matched = item;
    });
    if (!matched && path === "/app") {
      matched = { label: "首页", href: "/app" };
    }
    var title = String(document.title || "").split("·")[0].trim();
    return {
      id: path,
      label: (matched && matched.label) || title || "当前页面",
      href: path,
      kind: "page"
    };
  }

  function favoriteButtonHtml(meta) {
    if (!meta) return "";
    return (
      '<button type="button" class="icon-btn fav-page-btn" data-fav-id="' +
      escapeHtml(meta.id) +
      '" data-fav-label="' +
      escapeHtml(meta.label) +
      '" data-fav-href="' +
      escapeHtml(meta.href) +
      '" data-fav-kind="' +
      escapeHtml(meta.kind || "page") +
      '" aria-pressed="false" aria-label="收藏本页" title="收藏本页">' +
      starIcon() +
      "</button>"
    );
  }

  function syncFavoriteButtons() {
    var buttons = document.querySelectorAll("[data-fav-id]");
    Array.prototype.forEach.call(buttons, function (button) {
      var id = button.getAttribute("data-fav-id");
      var active = isFavorite(id);
      if (!button.querySelector("svg")) {
        button.innerHTML = starIcon();
      }
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
      var label = button.getAttribute("data-fav-label") || "该内容";
      button.setAttribute("aria-label", (active ? "取消收藏：" : "收藏：") + label);
      button.title = active ? "取消收藏" : "加入收藏";
    });
  }

  function showToast(message, variant) {
    var stack = document.getElementById("helper-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "helper-toast-stack";
      stack.className = "toast-stack";
      stack.setAttribute("role", "status");
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    var toast = document.createElement("div");
    toast.className = "toast" + (variant ? " toast-" + variant : "");
    toast.textContent = message;
    stack.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add("is-visible");
    });
    setTimeout(function () {
      toast.classList.remove("is-visible");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 220);
    }, 2200);
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest("[data-fav-id]") : null;
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    var result = toggleFavorite({
      id: button.getAttribute("data-fav-id"),
      label: button.getAttribute("data-fav-label"),
      href: button.getAttribute("data-fav-href"),
      kind: button.getAttribute("data-fav-kind")
    });
    showToast(result.active ? "已加入收藏" : "已取消收藏");
  });

  function buildNav(active) {
    var loggedIn = isLoggedIn();
    var items = loggedIn
      ? NAV_ITEMS.filter(function (item) {
          return !item.admin || isAdmin();
        })
      : NAV_ITEMS.filter(function (item) {
          return item.public === true;
        });

    var links = items.map(function (item) {
      var cls = "nav-link" + (item.key === active ? " active" : "");
      var href = item.key === "home" && loggedIn ? "/app" : item.href;
      return (
        '<a class="' +
        cls +
        '" href="' +
        href +
        '">' +
        escapeHtml(item.label) +
        "</a>"
      );
    }).join("");

    var actions =
      (loggedIn ? favoriteButtonHtml(pageFavoriteMeta()) : "") +
      '<button type="button" class="icon-btn theme-toggle" data-theme-toggle ' +
      'aria-label="切换深色或浅色主题" title="切换深色/浅色主题">' +
      themeIcons() +
      "</button>" +
      (loggedIn
        ? '<button type="button" class="btn btn-ghost btn-sm" data-helper-logout>退出登录</button>'
        : '<a class="btn btn-ghost btn-sm" href="/login">登录</a>' +
          '<a class="btn btn-primary btn-sm" href="/register">免费注册</a>');

    return (
      '<div class="nav-inner">' +
      '<a class="brand" href="' + (loggedIn ? "/app" : "/") + '">' +
      '<span class="brand-name">全国彩票购彩辅助工具</span>' +
      '<span class="brand-sub">合规记录 · 查询 · 提醒</span>' +
      "</a>" +
      '<nav class="nav-links" aria-label="主导航">' +
      links +
      "</nav>" +
      '<div class="nav-actions">' +
      actions +
      "</div>" +
      "</div>"
    );
  }

  function mountShell(active) {
    var header = document.getElementById("site-nav");
    if (header) {
      header.className = "site-header";
      header.innerHTML = buildNav(active || "");
      var logoutBtn = header.querySelector("[data-helper-logout]");
      if (logoutBtn) {
        logoutBtn.addEventListener("click", async function () {
          logoutBtn.disabled = true;
          try {
            await api("/api/helper/auth/logout", { method: "POST" });
          } catch (err) {
            /* 会话可能已失效，仍然本地退出 */
          }
          setLoggedIn(false);
          window.location.href = LOGIN_PAGE;
        });
      }

      var themeBtn = header.querySelector("[data-theme-toggle]");
      if (themeBtn && window.HelperTheme) {
        themeBtn.addEventListener("click", function () {
          window.HelperTheme.toggle();
        });
      }

      syncFavoriteButtons();
      subscribeFavorites(syncFavoriteButtons);
    }

    var footer = document.getElementById("site-footer");
    if (footer) {
      footer.className = "site-footer";
      footer.innerHTML =
        '<div class="footer-inner"><strong>合规提示：</strong>' +
        escapeHtml(COMPLIANCE_TEXT) +
        '<div class="footer-links">' +
        '<span class="footer-age">18+ 未成年人不得购彩</span>' +
        '<a href="/static/privacy.html">隐私政策</a>' +
        '<a href="/static/compliance.html">合规声明</a>' +
        "</div></div>";
    }
  }

  clearLegacyToken();

  window.isLoggedIn = isLoggedIn;
  window.setLoggedIn = setLoggedIn;
  window.isAdmin = isAdmin;
  window.setIsAdmin = setIsAdmin;
  window.api = api;
  window.mountShell = mountShell;
  window.escapeHtml = escapeHtml;
  window.fmtMoney = fmtMoney;
  window.fmtDate = fmtDate;
  window.showToast = showToast;
  window.HelperFavorites = {
    list: getFavorites,
    has: isFavorite,
    add: addFavorite,
    remove: removeFavorite,
    toggle: toggleFavorite,
    clear: clearFavorites,
    subscribe: subscribeFavorites,
    sync: syncFavoriteButtons
  };
})();
