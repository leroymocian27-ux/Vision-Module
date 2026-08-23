let images = [];
let currentIndex = 0;
let labels = [];
let selected = -1;
let drawing = null;

const imageList = document.getElementById("imageList");
const img = document.getElementById("image");
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");
const pageTitle = document.getElementById("pageTitle");
const sourceInfo = document.getElementById("sourceInfo");

async function init() {
  const batch = await (await fetch("/api/batch")).json();
  const batchId = batch.batch_id || "";
  pageTitle.textContent = `YOLO person labeler - ${batchId}`;
  document.title = `YOLO person ${batchId}`;
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
  selected = -1;
  const item = images[currentIndex];
  img.src = `/frames/${encodeURIComponent(item.image)}`;
  labels = (await (await fetch(`/api/label?image=${encodeURIComponent(item.image)}`)).json()).labels;
  statusEl.textContent = `${currentIndex + 1}/${images.length} ${item.image}`;
  sourceInfo.innerHTML = [
    `group: ${escapeHtml(item.group || "")}`,
    `scene: ${escapeHtml(item.scene || "")}`,
    `dataset: ${escapeHtml(item.source_dataset || "")}`,
    `video: ${escapeHtml(item.video_id || "")}`,
    `note: ${escapeHtml(item.note || "")}`,
  ].join("<br>");
  renderImageList();
  img.onload = renderBoxes;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

function renderBoxes() {
  [...stage.querySelectorAll(".box")].forEach(el => el.remove());
  const rect = img.getBoundingClientRect();
  labels.forEach((label, index) => {
    const div = document.createElement("div");
    div.className = `box ${index === selected ? "selected" : ""}`;
    div.style.left = `${(label.x - label.w / 2) * rect.width}px`;
    div.style.top = `${(label.y - label.h / 2) * rect.height}px`;
    div.style.width = `${label.w * rect.width}px`;
    div.style.height = `${label.h * rect.height}px`;
    div.onclick = event => {
      event.stopPropagation();
      selected = index;
      renderBoxes();
    };
    const tag = document.createElement("span");
    tag.textContent = "person";
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
  labels.push({ class_id: 0, x: (x1 + x2) / 2, y: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1 });
  selected = labels.length - 1;
  renderBoxes();
});

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

async function save(status = "reviewed") {
  const item = images[currentIndex];
  await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: item.image, labels, status }),
  });
  images[currentIndex].status = status;
  images[currentIndex].has_label = labels.length > 0;
  renderImageList();
  statusEl.textContent = `Saved ${item.image}`;
}

document.getElementById("saveBtn").onclick = () => save("reviewed");
document.getElementById("prevBtn").onclick = () => loadImage(currentIndex - 1);
document.getElementById("nextBtn").onclick = () => loadImage(currentIndex + 1);

window.addEventListener("resize", renderBoxes);
window.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") loadImage(currentIndex - 1);
  if (event.key === "ArrowRight") loadImage(currentIndex + 1);
  if (event.key === "Delete") document.getElementById("deleteBtn").click();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save("reviewed");
  }
});

init();
