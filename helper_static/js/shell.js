/* 纯展示页外壳：读取 body[data-active] 后渲染导航与页脚 */
(function () {
  "use strict";

  mountShell((document.body && document.body.dataset.active) || "");
})();
