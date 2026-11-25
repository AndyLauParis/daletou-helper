/* 意见反馈页：类型选择、文本与截图提交、状态提示、历史记录（无框架） */
(function () {
  "use strict";

  mountShell("feedback");

  var MAX_FILE_BYTES = 5 * 1024 * 1024;
  var ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];

  var form = document.getElementById("feedback-form");
  var contentEl = document.getElementById("feedback-content");
  var countEl = document.getElementById("feedback-count");
  var fileInput = document.getElementById("feedback-file");
  var uploadZone = document.getElementById("upload-zone");
  var previewWrap = document.getElementById("upload-preview");
  var previewImage = document.getElementById("upload-image");
  var previewName = document.getElementById("upload-name");
  var removeButton = document.getElementById("upload-remove");
  var errorBox = document.getElementById("feedback-error");
  var successBox = document.getElementById("feedback-success");
  var submitButton = document.getElementById("feedback-submit");

  var listEl = document.getElementById("feedback-list");
  var emptyEl = document.getElementById("feedback-empty");
  var totalEl = document.getElementById("feedback-total");
  var refreshButton = document.getElementById("feedback-refresh");

  var selectedFile = null;
  var previewUrl = "";

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function hideError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }

  function hideSuccess() {
    successBox.hidden = true;
    successBox.textContent = "";
  }

  function clearPreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }
    selectedFile = null;
    fileInput.value = "";
    previewImage.removeAttribute("src");
    previewWrap.hidden = true;
    previewName.textContent = "";
  }

  function chooseFile(file) {
    hideError();
    hideSuccess();
    if (!file) return;
    if (ALLOWED_TYPES.indexOf(file.type) === -1) {
      showError("截图仅支持 PNG、JPG 或 WebP 格式");
      clearPreview();
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      showError("截图不能超过 5 MB，请压缩后再试");
      clearPreview();
      return;
    }
    if (file.size === 0) {
      showError("截图文件为空，请重新选择");
      clearPreview();
      return;
    }
    clearPreview();
    selectedFile = file;
    previewUrl = URL.createObjectURL(file);
    previewImage.src = previewUrl;
    previewName.textContent = file.name + "（" + Math.ceil(file.size / 1024) + " KB）";
    previewWrap.hidden = false;
  }

  fileInput.addEventListener("change", function () {
    chooseFile(fileInput.files && fileInput.files[0]);
  });

  removeButton.addEventListener("click", function () {
    clearPreview();
  });

  uploadZone.addEventListener("dragover", function (event) {
    event.preventDefault();
    uploadZone.classList.add("is-dragging");
  });

  uploadZone.addEventListener("dragleave", function () {
    uploadZone.classList.remove("is-dragging");
  });

  uploadZone.addEventListener("drop", function (event) {
    event.preventDefault();
    uploadZone.classList.remove("is-dragging");
    var files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length) {
      chooseFile(files[0]);
    }
  });

  contentEl.addEventListener("input", function () {
    countEl.textContent = String(contentEl.value.length);
  });

  function category() {
    var checked = form.querySelector('input[name="category"]:checked');
    return checked ? checked.value : "suggestion";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    hideError();
    hideSuccess();

    var text = contentEl.value.trim();
    if (text.length < 5) {
      showError("反馈内容至少需要 5 个字符");
      contentEl.focus();
      return;
    }
    if (text.length > 1000) {
      showError("反馈内容最多 1000 个字符");
      return;
    }

    var payload = new FormData();
    payload.append("category", category());
    payload.append("content", text);
    if (selectedFile) {
      payload.append("screenshot", selectedFile, selectedFile.name);
    }

    submitButton.disabled = true;
    submitButton.textContent = "提交中…";

    api("/api/helper/feedback", { method: "POST", body: payload })
      .then(function (item) {
        form.reset();
        countEl.textContent = "0";
        clearPreview();
        successBox.textContent =
          "反馈已提交，编号 #" +
          item.id +
          "。感谢你的帮助，我们会在后续改进中参考。";
        successBox.hidden = false;
        showToast("反馈提交成功");
        loadHistory();
      })
      .catch(function (err) {
        showError(err.message || "提交失败，请稍后重试");
      })
      .finally(function () {
        submitButton.disabled = false;
        submitButton.textContent = "提交反馈";
      });
  });

  function renderHistory(items, total) {
    var list = Array.isArray(items) ? items : [];
    totalEl.textContent =
      "仅显示当前账号提交的记录，共 " + (total || list.length) + " 条。";
    emptyEl.hidden = list.length > 0;
    listEl.innerHTML = list
      .map(function (item) {
        var shot =
          item.has_screenshot === true
            ? '<a class="feedback-shot" href="/api/helper/feedback/' +
              encodeURIComponent(item.id) +
              '/screenshot" target="_blank" rel="noopener">' +
              '<img src="/api/helper/feedback/' +
              encodeURIComponent(item.id) +
              '/screenshot" alt="反馈截图" loading="lazy"></a>'
            : "";
        return (
          '<article class="feedback-item">' +
          '<div class="feedback-item-head">' +
          '<span class="badge badge-soft">' +
          escapeHtml(item.category_label || item.category) +
          "</span>" +
          '<span class="feedback-id">#' +
          escapeHtml(item.id) +
          "</span>" +
          '<time class="feedback-time">' +
          escapeHtml(fmtDate(item.created_at)) +
          "</time>" +
          "</div>" +
          '<p class="feedback-content">' +
          escapeHtml(item.content) +
          "</p>" +
          shot +
          "</article>"
        );
      })
      .join("");
  }

  function loadHistory() {
    refreshButton.disabled = true;
    api("/api/helper/feedback?limit=20")
      .then(function (data) {
        renderHistory(data.items, data.total);
      })
      .catch(function (err) {
        totalEl.textContent = "历史记录加载失败";
        showError(err.message || "历史记录加载失败，请稍后重试");
      })
      .finally(function () {
        refreshButton.disabled = false;
      });
  }

  refreshButton.addEventListener("click", loadHistory);

  loadHistory();
})();
