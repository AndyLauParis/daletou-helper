/* 主题引导：在 <head> 中同步执行，先于页面绘制应用主题，避免闪烁。 */
(function () {
  "use strict";

  var STORAGE_KEY = "helper_theme";
  var root = document.documentElement;

  function readMode() {
    try {
      var value = localStorage.getItem(STORAGE_KEY);
      return value === "light" || value === "dark" ? value : "auto";
    } catch (err) {
      return "auto";
    }
  }

  function systemDark() {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch (err) {
      return false;
    }
  }

  function resolve(mode) {
    return mode === "dark" || (mode === "auto" && systemDark())
      ? "dark"
      : "light";
  }

  function apply(mode) {
    var theme = resolve(mode);
    root.setAttribute("data-theme", theme);
    root.setAttribute("data-theme-mode", mode);
    root.style.colorScheme = theme;
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) {
      meta.setAttribute("content", theme === "dark" ? "dark light" : "light dark");
    }
  }

  function emit(mode) {
    try {
      window.dispatchEvent(
        new CustomEvent("helper:theme-changed", {
          detail: { mode: mode, theme: resolve(mode) }
        })
      );
    } catch (err) {
      /* ignore */
    }
  }

  function setMode(mode) {
    var next = mode === "light" || mode === "dark" ? mode : "auto";
    try {
      if (next === "auto") {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, next);
      }
    } catch (err) {
      /* 隐私模式下仅当前页面生效 */
    }
    apply(next);
    emit(next);
  }

  apply(readMode());

  try {
    var query = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () {
      if (readMode() === "auto") {
        apply("auto");
        emit("auto");
      }
    };
    if (query.addEventListener) {
      query.addEventListener("change", onChange);
    } else if (query.addListener) {
      query.addListener(onChange);
    }
  } catch (err) {
    /* ignore */
  }

  window.addEventListener("storage", function (event) {
    if (event.key === STORAGE_KEY || event.key === null) {
      apply(readMode());
      emit(readMode());
    }
  });

  window.HelperTheme = {
    getMode: readMode,
    getTheme: function () {
      return resolve(readMode());
    },
    setMode: setMode,
    toggle: function () {
      setMode(resolve(readMode()) === "dark" ? "light" : "dark");
    }
  };
})();
