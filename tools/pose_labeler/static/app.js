let images = [];
let keypointNames = [];
let currentIndex = 0;
let annotations = [];
let personIndex = 0;
let pointIndex = 0;

const imageList = document.getElementById("imageList");
const img = document.getElementById("image");
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");
const pageTitle = document.getElementById("pageTitle");
const sourceInfo = document.getElementById("sourceInfo");
const personSelect = document.getElementById("personSelect");
const currentPoint = document.getElementById("currentPoint");
const kpList = document.getElementById("kpList");

async function init() {
  const batch = await (await fetch("/api/batch")).json();
  keypointNames = batch.keypoints || [];
  pageTitle.textContent = `YOLO pose labeler - ${batch.batch_id || ""}`;
  document.title = `YOLO pose ${batch.batch_id || ""}`;
  images = (await (await fetch("/api/images")).json()).images;
  renderImageList();
  await loadImage(0);
}

function renderImageList() {
  imageList.innerHTML = "";
  images.forEach((item, index) => {
    const btn = document.createElement("button");
    btn.textContent = `${index + 1}. ${item.image}`;
    btn.className = `${index === currentIndex ? "active" : ""} ${item.status === "reviewed" ? "reviewed" : ""}`;
    btn.onclick = () => loadImage(index);
    imageList.appendChild(btn);
  });
}

async function loadImage(index) {
  if (index < 0 || index >= images.length) return;
  currentIndex = index;
  personIndex = 0;
  pointIndex = 0;
  const item = images[currentIndex];
  img.onload = renderOverlay;
  img.src = `/frames/${encodeURIComponent(item.image)}`;
  const payload = await (await fetch(`/api/label?image=${encodeURIComponent(item.image)}`)).json();
  annotations = payload.annotations || [];
  normalizeAnnotations();
  statusEl.textContent = `${currentIndex + 1}/${images.length} ${item.image}`;
  sourceInfo.innerHTML = [
    `group: ${escapeHtml(item.group || "")}`,
    `scene: ${escapeHtml(item.scene || "")}`,
    `dataset: ${escapeHtml(item.source_dataset || "")}`,
    `video: ${escapeHtml(item.video_id || "")}`,
    `persons: ${escapeHtml(item.person_boxes || "")}`,
  ].join("<br>");
  renderImageList();
  renderPersonSelect();
  renderKpList();
  if (img.complete) renderOverlay();
}

function normalizeAnnotations() {
  annotations.forEach(ann => {
    ann.bbox ||= { x: 0.5, y: 0.5, w: 0.1, h: 0.1 };
    const existing = {};
    (ann.keypoints || []).forEach(kp => { existing[kp.name] = kp; });
    ann.keypoints = keypointNames.map(name => {
      const old = existing[name] || {};
      return { name, x: Number(old.x || 0), y: Number(old.y || 0), v: Number(old.v || 0) };
    });
  });
}

function renderPersonSelect() {
  personSelect.innerHTML = "";
  annotations.forEach((ann, index) => {
    const opt = document.createElement("option");
    const done = countDone(ann);
    opt.value = String(index);
    opt.textContent = `person ${index + 1} (${done}/${keypointNames.length})`;
    personSelect.appendChild(opt);
  });
  personSelect.value = String(Math.min(personIndex, annotations.length - 1));
}

personSelect.onchange = () => {
  personIndex = Number(personSelect.value || 0);
  pointIndex = firstUnmarkedIndex(annotations[personIndex]) ?? 0;
  renderAll();
};

function renderAll() {
  renderPersonSelect();
  renderKpList();
  renderOverlay();
}

function renderOverlay() {
  [...stage.querySelectorAll(".box,.kp")].forEach(el => el.remove());
  const rect = img.getBoundingClientRect();
  annotations.forEach((ann, index) => {
    const box = ann.bbox;
    const div = document.createElement("div");
    div.className = `box ${index === personIndex ? "active" : ""}`;
    div.style.left = `${(box.x - box.w / 2) * rect.width}px`;
    div.style.top = `${(box.y - box.h / 2) * rect.height}px`;
    div.style.width = `${box.w * rect.width}px`;
    div.style.height = `${box.h * rect.height}px`;
    stage.appendChild(div);

    ann.keypoints.forEach((kp, kpIndex) => {
      if (kp.v <= 0) return;
      const dot = document.createElement("div");
      dot.className = `kp ${index === personIndex && kpIndex === pointIndex ? "current" : ""}`;
      dot.style.left = `${kp.x * rect.width}px`;
      dot.style.top = `${kp.y * rect.height}px`;
      dot.title = `${index + 1}: ${kp.name}`;
      dot.onclick = event => {
        event.stopPropagation();
        personIndex = index;
        pointIndex = kpIndex;
        renderAll();
      };
      stage.appendChild(dot);
    });
  });
}

function renderKpList() {
  const ann = annotations[personIndex];
  kpList.innerHTML = "";
  if (!ann) {
    currentPoint.textContent = "No person bbox in this image.";
    return;
  }
  const kp = ann.keypoints[pointIndex];
  currentPoint.textContent = `person ${personIndex + 1}: ${pointIndex + 1}. ${kp.name}`;
  ann.keypoints.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `kp-row ${index === pointIndex ? "current" : ""} ${item.v > 0 ? "done" : "missing"}`;
    row.textContent = `${index + 1}. ${item.name}`;
    const btn = document.createElement("button");
    btn.textContent = item.v > 0 ? "set" : "missing";
    btn.onclick = () => {
      pointIndex = index;
      renderAll();
    };
    kpList.appendChild(row);
    kpList.appendChild(btn);
  });
}

stage.addEventListener("click", event => {
  if (event.target !== img && event.target !== stage) return;
  const ann = annotations[personIndex];
  if (!ann) return;
  const p = pointerToNorm(event);
  ann.keypoints[pointIndex] = { name: keypointNames[pointIndex], x: p.x, y: p.y, v: 2 };
  advancePoint();
  renderAll();
});

function pointerToNorm(event) {
  const rect = img.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
  return { x, y };
}

function markMissing() {
  const ann = annotations[personIndex];
  if (!ann) return;
  ann.keypoints[pointIndex] = { name: keypointNames[pointIndex], x: 0, y: 0, v: 0 };
  advancePoint();
  renderAll();
}

function advancePoint() {
  if (pointIndex < keypointNames.length - 1) {
    pointIndex += 1;
    return;
  }
  if (personIndex < annotations.length - 1) {
    personIndex += 1;
    pointIndex = firstUnmarkedIndex(annotations[personIndex]) ?? 0;
  }
}

function firstUnmarkedIndex(ann) {
  if (!ann) return null;
  const index = ann.keypoints.findIndex(kp => kp.v === 0 && kp.x === 0 && kp.y === 0);
  return index >= 0 ? index : null;
}

function countDone(ann) {
  return (ann.keypoints || []).filter(kp => kp.v > 0).length;
}

document.getElementById("missingBtn").onclick = markMissing;
document.getElementById("resetPersonBtn").onclick = () => {
  const ann = annotations[personIndex];
  if (!ann) return;
  ann.keypoints = keypointNames.map(name => ({ name, x: 0, y: 0, v: 0 }));
  pointIndex = 0;
  renderAll();
};

async function save(status = "reviewed") {
  const item = images[currentIndex];
  await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: item.image, annotations, status }),
  });
  images[currentIndex].status = status;
  renderImageList();
  renderPersonSelect();
  statusEl.textContent = `Saved ${item.image}`;
}

document.getElementById("saveBtn").onclick = () => save("reviewed");
document.getElementById("prevBtn").onclick = () => loadImage(currentIndex - 1);
document.getElementById("nextBtn").onclick = () => loadImage(currentIndex + 1);

window.addEventListener("resize", renderOverlay);
window.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") loadImage(currentIndex - 1);
  if (event.key === "ArrowRight") loadImage(currentIndex + 1);
  if (event.key.toLowerCase() === "m") markMissing();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save("reviewed");
  }
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

init();
