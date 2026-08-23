let labelClasses = [];
let labelClassOptions = [];
let reviewClassOptions = [];
let images = [];
let currentIndex = 0;
let labels = [];
let selected = -1;
let drawing = null;
let showPendingOnly = false;
let activeItem = null;

const imageList = document.getElementById("imageList");
const img = document.getElementById("image");
const stage = document.getElementById("stage");
const labelClassSelect = document.getElementById("labelClassSelect");
const correctClassSelect = document.getElementById("correctClassSelect");
const statusEl = document.getElementById("status");
const progressStatus = document.getElementById("progressStatus");
const pageTitle = document.getElementById("pageTitle");
const sourceInfo = document.getElementById("sourceInfo");
const reviewInfo = document.getElementById("reviewInfo");
const queueInfo = document.getElementById("queueInfo");
const rejectReasonInput = document.getElementById("rejectReason");
const reviewNotesInput = document.getElementById("reviewNotes");
const pendingOnlyToggle = document.getElementById("pendingOnlyToggle");

async function init() {
  showPendingOnly = window.localStorage.getItem("fallHintLabeler.showPendingOnly") === "1";
  pendingOnlyToggle.checked = showPendingOnly;

  const batch = await (await fetch("/api/batch")).json();
  const batchId = batch.batch_id || "";
  pageTitle.textContent = `Fall Hint Boundary Review - ${batchId}`;
  document.title = `Fall Hint Boundary Review - ${batchId}`;

  const classesPayload = await (await fetch("/api/classes")).json();
  labelClasses = classesPayload.classes || [];
  labelClassOptions = classesPayload.label_class_options || [];
  reviewClassOptions = classesPayload.review_class_options || [];

  labelClassSelect.innerHTML = labelClassOptions
    .map(option => `<option value="${option.id}">${escapeHtml(option.name)}</option>`)
    .join("");
  correctClassSelect.innerHTML = [
    `<option value="">保持当前</option>`,
    ...reviewClassOptions.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
  ].join("");

  images = (await (await fetch("/api/images")).json()).images || [];
  renderImageList();
  await updateProgress();
  const startIndex = findFirstPendingIndex();
  await loadImage(startIndex >= 0 ? startIndex : 0);
}

function renderImageList() {
  imageList.innerHTML = "";
  const visibleItems = showPendingOnly ? images.filter(item => item.review_decision === "pending") : images;
  visibleItems.forEach((item) => {
    const index = images.findIndex(candidate => candidate.image === item.image);
    const btn = document.createElement("button");
    btn.className = [
      index === currentIndex ? "active" : "",
      item.review_decision !== "pending" ? "reviewed" : "",
      `decision-${item.review_decision || "pending"}`,
    ].join(" ").trim();
    btn.textContent = `${String(index + 1).padStart(2, "0")} ${item.image} [${decisionLabel(item.review_decision)}]`;
    btn.onclick = () => loadImage(index);
    imageList.appendChild(btn);
    if (index === currentIndex) {
      requestAnimationFrame(() => btn.scrollIntoView({ block: "nearest" }));
    }
  });
}

async function updateProgress() {
  const payload = await (await fetch("/api/progress")).json();
  const progress = payload.progress || {};
  const decisionCounts = progress.decision_counts || {};
  progressStatus.textContent =
    `Reviewed ${progress.reviewed || 0}/${progress.total || 0} | Pending ${progress.remaining || 0}` +
    ` | train ${decisionCounts.pass_train || 0}` +
    ` | val ${decisionCounts.pass_val || 0}` +
    ` | reject ${decisionCounts.reject || 0}` +
    ` | needs_fix ${decisionCounts.needs_fix || 0}`;
}

function findFirstPendingIndex() {
  return images.findIndex(item => item.review_decision === "pending");
}

function findNextPendingIndex(startIndex = currentIndex) {
  if (!images.length) return -1;
  for (let offset = 1; offset <= images.length; offset += 1) {
    const index = (startIndex + offset) % images.length;
    if (images[index].review_decision === "pending") {
      return index;
    }
  }
  return -1;
}

async function loadImage(index) {
  if (!images.length) return;
  if (index < 0) index = 0;
  if (index >= images.length) index = images.length - 1;

  currentIndex = index;
  selected = -1;
  const item = images[currentIndex];
  const payload = await (await fetch(`/api/item?image=${encodeURIComponent(item.image)}`)).json();
  activeItem = payload.item || item;
  labels = payload.labels || [];
  images[currentIndex] = { ...images[currentIndex], ...activeItem };
  img.src = `/frames/${encodeURIComponent(activeItem.image)}`;

  statusEl.textContent = `${currentIndex + 1}/${images.length} ${activeItem.image}`;
  sourceInfo.innerHTML = [
    fieldLine("source_batch", activeItem.source_batch_id),
    fieldLine("video", activeItem.video_id),
    fieldLine("scene", activeItem.scene),
    fieldLine("group", activeItem.group),
    fieldLine("original", activeItem.source_original_image),
    fieldLine("source_video", activeItem.source_video),
  ].join("");
  reviewInfo.innerHTML = [
    fieldLine("item_id", activeItem.item_id),
    fieldLine("boundary_category", activeItem.boundary_category),
    fieldLine("related_failure_case", activeItem.related_failure_case),
    fieldLine("similarity_reason", activeItem.similarity_reason),
    fieldLine("expected_help", activeItem.expected_help),
    fieldLine("current_class", activeItem.current_class || activeItem.current_label_class_name || ""),
    fieldLine("current_label", activeItem.current_label_class_name || ""),
  ].join("");
  queueInfo.innerHTML = [
    fieldLine("decision", decisionLabel(activeItem.review_decision)),
    fieldLine("usable_for_training", activeItem.usable_for_training || "pending"),
    fieldLine("usable_for_validation", activeItem.usable_for_validation || "pending"),
    fieldLine("target_image_path", activeItem.target_image_path || ""),
    fieldLine("target_label_path", activeItem.target_label_path || ""),
  ].join("");

  if (typeof activeItem.current_label_class_id === "number") {
    labelClassSelect.value = String(activeItem.current_label_class_id);
  } else if (labelClassOptions.length) {
    labelClassSelect.value = String(labelClassOptions[0].id);
  }

  correctClassSelect.value = activeItem.correct_class || "";
  rejectReasonInput.value = activeItem.reject_reason || "";
  reviewNotesInput.value = activeItem.review_notes || "";

  renderImageList();
  img.onload = renderBoxes;
  renderBoxes();
}

function fieldLine(label, value) {
  return `<div class="field-line"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></div>`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

function decisionLabel(decision) {
  const mapping = {
    pending: "pending",
    pass_train: "pass_train",
    pass_val: "pass_val",
    reject: "reject",
    needs_fix: "needs_fix",
  };
  return mapping[decision || "pending"] || "pending";
}

function renderBoxes() {
  [...stage.querySelectorAll(".box")].forEach(el => el.remove());
  const rect = img.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  labels.forEach((label, index) => {
    const div = document.createElement("div");
    div.className = `box ${index === selected ? "selected" : ""}`;
    const left = (label.x - label.w / 2) * rect.width;
    const top = (label.y - label.h / 2) * rect.height;
    div.style.left = `${left}px`;
    div.style.top = `${top}px`;
    div.style.width = `${label.w * rect.width}px`;
    div.style.height = `${label.h * rect.height}px`;
    div.onclick = (event) => {
      event.stopPropagation();
      selected = index;
      labelClassSelect.value = String(label.class_id);
      renderBoxes();
    };

    const tag = document.createElement("span");
    tag.textContent = labelClasses[label.class_id] || String(label.class_id);
    div.appendChild(tag);
    stage.appendChild(div);
  });
}

function pointerToNorm(event) {
  const rect = img.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
  return { x, y };
}

stage.addEventListener("mousedown", event => {
  if (event.target !== img && event.target !== stage) return;
  drawing = pointerToNorm(event);
});

stage.addEventListener("mouseup", event => {
  if (!drawing) return;
  const end = pointerToNorm(event);
  const x1 = Math.min(drawing.x, end.x);
  const y1 = Math.min(drawing.y, end.y);
  const x2 = Math.max(drawing.x, end.x);
  const y2 = Math.max(drawing.y, end.y);
  drawing = null;
  if (x2 - x1 < 0.01 || y2 - y1 < 0.01) return;

  labels.push({
    class_id: Number(labelClassSelect.value),
    x: (x1 + x2) / 2,
    y: (y1 + y2) / 2,
    w: x2 - x1,
    h: y2 - y1,
  });
  selected = labels.length - 1;
  renderBoxes();
});

document.getElementById("applyClassBtn").onclick = () => {
  if (selected < 0) return;
  labels[selected].class_id = Number(labelClassSelect.value);
  renderBoxes();
};

document.getElementById("deleteBtn").onclick = () => {
  if (selected < 0) return;
  labels.splice(selected, 1);
  selected = -1;
  renderBoxes();
};

document.getElementById("emptyBtn").onclick = () => {
  labels = [];
  selected = -1;
  renderBoxes();
};

async function saveLabels(status = "draft", refreshProgress = true) {
  const item = images[currentIndex];
  await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: item.image, labels, status }),
  });
  statusEl.textContent = `Saved bbox for ${item.image}`;
  if (refreshProgress) {
    await updateProgress();
  }
}

async function submitDecision(decision) {
  const item = images[currentIndex];
  const correctClass = correctClassSelect.value || (activeItem.current_label_class_name || activeItem.current_class || "");

  let usableForTraining = "pending";
  let usableForValidation = "pending";
  if (decision === "pass_train") {
    usableForTraining = "true";
    usableForValidation = "false";
  } else if (decision === "pass_val") {
    usableForTraining = "false";
    usableForValidation = "true";
  } else if (decision === "reject") {
    usableForTraining = "false";
    usableForValidation = "false";
  }

  await saveLabels(decision === "pending" ? "draft" : "reviewed", false);
  const response = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image: item.image,
      review_decision: decision,
      correct_class: correctClass,
      usable_for_training: usableForTraining,
      usable_for_validation: usableForValidation,
      reject_reason: rejectReasonInput.value.trim(),
      review_notes: reviewNotesInput.value.trim(),
    }),
  });
  await response.json();

  images[currentIndex] = {
    ...images[currentIndex],
    review_decision: decision,
    correct_class: correctClass,
    usable_for_training: usableForTraining,
    usable_for_validation: usableForValidation,
    reject_reason: rejectReasonInput.value.trim(),
    review_notes: reviewNotesInput.value.trim(),
    status: decision === "pending" ? "draft" : "reviewed",
  };
  renderImageList();
  await updateProgress();

  const nextPendingIndex = findNextPendingIndex(currentIndex);
  if (nextPendingIndex >= 0 && nextPendingIndex !== currentIndex) {
    await loadImage(nextPendingIndex);
    statusEl.textContent = `Saved ${decision} and moved to ${images[nextPendingIndex].image}`;
    return;
  }
  await loadImage(currentIndex);
  statusEl.textContent = `Saved ${decision}. No more pending items.`;
}

document.getElementById("saveBtn").onclick = () => saveLabels("draft");
document.getElementById("passTrainBtn").onclick = () => submitDecision("pass_train");
document.getElementById("passValBtn").onclick = () => submitDecision("pass_val");
document.getElementById("needsFixBtn").onclick = () => submitDecision("needs_fix");
document.getElementById("rejectBtn").onclick = () => submitDecision("reject");
document.getElementById("prevBtn").onclick = () => loadImage(currentIndex - 1);
document.getElementById("nextBtn").onclick = () => loadImage(currentIndex + 1);
document.getElementById("nextPendingBtn").onclick = () => {
  const nextPendingIndex = findNextPendingIndex(currentIndex);
  if (nextPendingIndex >= 0 && nextPendingIndex !== currentIndex) {
    loadImage(nextPendingIndex);
  } else {
    statusEl.textContent = "No remaining pending items.";
  }
};
document.getElementById("jumpPendingBtn").onclick = () => {
  const firstPendingIndex = findFirstPendingIndex();
  if (firstPendingIndex >= 0) {
    loadImage(firstPendingIndex);
  } else {
    statusEl.textContent = "No pending items.";
  }
};

pendingOnlyToggle.onchange = () => {
  showPendingOnly = pendingOnlyToggle.checked;
  window.localStorage.setItem("fallHintLabeler.showPendingOnly", showPendingOnly ? "1" : "0");
  if (showPendingOnly && images[currentIndex] && images[currentIndex].review_decision !== "pending") {
    const firstPendingIndex = findFirstPendingIndex();
    if (firstPendingIndex >= 0) {
      loadImage(firstPendingIndex);
      return;
    }
  }
  renderImageList();
};

window.addEventListener("resize", renderBoxes);
window.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") loadImage(currentIndex - 1);
  if (event.key === "ArrowRight") loadImage(currentIndex + 1);
  if (event.key === "Delete") document.getElementById("deleteBtn").click();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveLabels("draft");
  }
  if (event.shiftKey && event.key.toLowerCase() === "t") {
    event.preventDefault();
    submitDecision("pass_train");
  }
  if (event.shiftKey && event.key.toLowerCase() === "v") {
    event.preventDefault();
    submitDecision("pass_val");
  }
  if (event.shiftKey && event.key.toLowerCase() === "r") {
    event.preventDefault();
    submitDecision("reject");
  }
  if (event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    submitDecision("needs_fix");
  }
});

init();
