/* 全国彩票购彩辅助工具 —— 公共前端脚本（无框架、无外部依赖） */
(function () {
  "use strict";

  var TOKEN_KEY = "helper_token";
  var LOGIN_PAGE = "/login";

  var NAV_ITEMS = [
    { key: "home", label: "首页", href: "/" },
    { key: "games", label: "游戏目录", href: "/static/games.html" },
    { key: "numbers", label: "号码本", href: "/static/numbers.html" },
    { key: "budget", label: "预算", href: "/static/budget.html" },
    { key: "draws", label: "开奖核对", href: "/static/draws.html" },
    { key: "reminders", label: "提醒", href: "/static/reminders.html" },
    { key: "settings", label: "设置", href: "/static/settings.html" }
  ];

  var COMPLIANCE_TEXT =
    "本工具仅提供记录、查询与提醒，不代购、不支付、不出票、不承诺中奖；" +
    "请通过官方线下渠道购彩；未成年人不得购彩。";

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch (err) {
      return "";
    }
  }

  function setToken(token) {
    try {
      localStorage.setItem(TOKEN_KEY, token || "");
    } catch (err) {
      /* 隐私模式下忽略写入失败 */
    }
  }

  function clearToken() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch (err) {
      /* ignore */
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
    var token = getToken();
    if (token) headers.set("Authorization", "Bearer " + token);
    if (typeof opts.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    opts.headers = headers;

    var response;
    try {
      response = await fetch(path, opts);
    } catch (err) {
      throw new Error("网络异常，请检查网络后重试");
    }

    if (response.status === 401) {
      clearToken();
      if (
        window.location.pathname !== "/login" &&
        window.location.pathname !== "/register"
      ) {
        window.location.href = LOGIN_PAGE;
      }
      throw new Error(await readDetail(response, "请先登录"));
    }

    if (!response.ok) {
      throw new Error(
        await readDetail(response, "请求失败（" + response.status + "）")
      );
    }

    if (response.status === 204) return null;
    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") !== -1) {
      return response.json();
    }
    return response.text();
  }

  function buildNav(active) {
    var links = NAV_ITEMS.map(function (item) {
      var cls = "nav-link" + (item.key === active ? " active" : "");
      return (
        '<a class="' +
        cls +
        '" href="' +
        item.href +
        '">' +
        escapeHtml(item.label) +
        "</a>"
      );
    }).join("");

    var actions = getToken()
      ? '<button type="button" class="btn btn-ghost btn-sm" data-helper-logout>退出登录</button>'
      : '<a class="btn btn-ghost btn-sm" href="/login">登录</a>';

    return (
      '<div class="nav-inner">' +
      '<a class="brand" href="/">' +
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
            /* 令牌可能已失效，仍然本地退出 */
          }
          clearToken();
          window.location.href = LOGIN_PAGE;
        });
      }
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

  window.getToken = getToken;
  window.setToken = setToken;
  window.clearToken = clearToken;
  window.api = api;
  window.mountShell = mountShell;
  window.escapeHtml = escapeHtml;
  window.fmtMoney = fmtMoney;
  window.fmtDate = fmtDate;
})();
