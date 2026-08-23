from __future__ import annotations

import csv
import json
import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
BATCH_ROOT: Path
FRAMES_DIR: Path
DRAFT_LABELS_DIR: Path
REVIEW_LABELS_DIR: Path
REVIEW_META_DIR: Path
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_CLASSES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]
REVIEW_CLASS_DISPLAY_ORDER = [
    "standing",
    "sitting",
    "lying",
    "bending",
    "kneeling",
    "falling",
    "fallen",
]
REVIEW_DECISIONS = {"pending", "pass_train", "pass_val", "reject", "needs_fix"}
TRI_STATE = {"pending", "true", "false"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
REVIEW_QUEUE_FIELDS = [
    "item_id",
    "boundary_category",
    "related_failure_case",
    "target_image_path",
    "target_label_path",
    "current_class",
    "correct_class",
    "review_decision",
    "usable_for_training",
    "usable_for_validation",
    "reject_reason",
    "review_notes",
    "similarity_reason",
    "expected_help",
]


class FallHintLabelerHandler(BaseHTTPRequestHandler):
    server_version = "FallHintLabeler/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/classes":
            self._send_json(
                {
                    "classes": read_label_classes(),
                    "label_class_options": build_label_class_options(read_label_classes()),
                    "review_class_options": REVIEW_CLASS_DISPLAY_ORDER,
                }
            )
            return
        if parsed.path == "/api/batch":
            self._send_json({"batch_id": BATCH_ROOT.name})
            return
        if parsed.path == "/api/images":
            self._send_json({"images": list_images()})
            return
        if parsed.path == "/api/progress":
            self._send_json({"progress": build_progress()})
            return
        if parsed.path == "/api/label":
            query = parse_qs(parsed.query)
            image = safe_name(query.get("image", [""])[0])
            self._send_json({"image": image, "labels": read_labels(image)})
            return
        if parsed.path == "/api/item":
            query = parse_qs(parsed.query)
            image = safe_name(query.get("image", [""])[0])
            self._send_json({"item": build_item(image), "labels": read_labels(image)})
            return
        if parsed.path.startswith("/frames/"):
            image = safe_name(unquote(parsed.path.removeprefix("/frames/")))
            self._send_file(FRAMES_DIR / image, mimetypes.guess_type(image)[0] or "application/octet-stream")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/label":
            payload = self._read_json_body()
            image = safe_name(str(payload.get("image") or ""))
            labels = payload.get("labels")
            status = normalize_status(str(payload.get("status") or "draft"))
            if not isinstance(labels, list):
                self.send_error(400, "labels must be a list")
                return
            write_labels(image, labels, status=status)
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/review":
            payload = self._read_json_body()
            image = safe_name(str(payload.get("image") or ""))
            updated = update_review_row(
                image=image,
                review_decision=str(payload.get("review_decision") or "pending"),
                correct_class=str(payload.get("correct_class") or "").strip(),
                usable_for_training=str(payload.get("usable_for_training") or "pending"),
                usable_for_validation=str(payload.get("usable_for_validation") or "pending"),
                reject_reason=str(payload.get("reject_reason") or "").strip(),
                review_notes=str(payload.get("review_notes") or "").strip(),
            )
            self._send_json({"ok": True, "row": updated, "summary": summarize_review_queue()})
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[labeler] {self.address_string()} - {fmt % args}")

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("payload must be an object")
        return data

    def _send_json(self, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def safe_name(value: str) -> str:
    name = Path(value).name
    if not name:
        raise ValueError("empty file name")
    return name


def normalize_status(value: str) -> str:
    return "reviewed" if value == "reviewed" else "draft"


def read_label_classes() -> list[str]:
    candidates = [
        BATCH_ROOT / "classes.txt",
        BATCH_ROOT / "prelabels" / "hf_human_fall_yolo11_mapped" / "classes.txt",
    ]
    for path in candidates:
        if not path.exists():
            continue
        values = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if values:
            return values
    return list(DEFAULT_CLASSES)


def build_label_class_options(classes: list[str]) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for name in REVIEW_CLASS_DISPLAY_ORDER:
        if name not in classes:
            continue
        options.append({"id": classes.index(name), "name": name})
    for index, name in enumerate(classes):
        if any(option["id"] == index for option in options):
            continue
        options.append({"id": index, "name": name})
    return options


def list_images() -> list[dict[str, object]]:
    ensure_review_seeded()
    images = sorted(path.name for path in FRAMES_DIR.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    return [build_item(image) for image in images]


def build_item(image: str) -> dict[str, object]:
    ensure_review_seeded()
    frame_meta = read_frame_manifest()
    queue_index = read_review_queue_index()
    meta = frame_meta.get(image, {})
    review_row = queue_index.get(image, {})
    labels = read_labels(image)
    primary_class_id = labels[0]["class_id"] if labels else None
    label_classes = read_label_classes()
    primary_class_name = (
        label_classes[primary_class_id] if isinstance(primary_class_id, int) and 0 <= primary_class_id < len(label_classes) else ""
    )

    decision = str(review_row.get("review_decision") or "pending")
    if decision not in REVIEW_DECISIONS:
        decision = "pending"

    status = "reviewed" if decision != "pending" else read_label_status(image)
    current_class = str(review_row.get("current_class") or meta.get("class_name") or primary_class_name or "")
    correct_class = str(review_row.get("correct_class") or "")

    return {
        "image": image,
        "status": status,
        "has_label": bool(labels),
        "video_id": meta.get("video_id", ""),
        "scene": meta.get("scene", ""),
        "group": meta.get("group", ""),
        "source_batch_id": meta.get("source_batch_id", ""),
        "source_original_image": meta.get("source_original_image", ""),
        "source_video": meta.get("source_video", ""),
        "source_manifest_index": meta.get("source_manifest_index", ""),
        "boundary_category": review_row.get("boundary_category", meta.get("boundary_category", "")),
        "related_failure_case": review_row.get("related_failure_case", meta.get("related_failure_case", "")),
        "similarity_reason": review_row.get("similarity_reason", meta.get("similarity_reason", "")),
        "expected_help": review_row.get("expected_help", meta.get("expected_help", "")),
        "target_image_path": review_row.get("target_image_path", str(FRAMES_DIR / image)),
        "target_label_path": review_row.get("target_label_path", str(REVIEW_LABELS_DIR / f"{Path(image).stem}.txt")),
        "item_id": review_row.get("item_id", meta.get("item_id", Path(image).stem)),
        "current_class": current_class,
        "correct_class": correct_class,
        "review_decision": decision,
        "usable_for_training": normalize_tri_state(review_row.get("usable_for_training", "pending")),
        "usable_for_validation": normalize_tri_state(review_row.get("usable_for_validation", "pending")),
        "reject_reason": review_row.get("reject_reason", ""),
        "review_notes": review_row.get("review_notes", ""),
        "current_label_class_id": primary_class_id,
        "current_label_class_name": primary_class_name,
        "box_count": len(labels),
    }


def build_progress() -> dict[str, int | dict[str, int]]:
    items = list_images()
    total = len(items)
    reviewed = sum(
        1
        for item in items
        if item.get("review_decision") != "pending" or item.get("status") == "reviewed"
    )
    draft = total - reviewed
    decision_counts: dict[str, int] = {}
    for item in items:
        decision = str(item.get("review_decision") or "pending")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    return {
        "total": total,
        "reviewed": reviewed,
        "draft": draft,
        "remaining": max(0, total - reviewed),
        "decision_counts": decision_counts,
    }


def read_frame_manifest() -> dict[str, dict[str, str]]:
    candidates = [BATCH_ROOT / "meta" / "frame_manifest.csv", BATCH_ROOT / "meta" / "source_manifest.csv"]
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8-sig") as fh:
            return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}
    return {}


def read_review_queue_rows() -> tuple[list[dict[str, str]], list[str]]:
    path = BATCH_ROOT / "meta" / "review_queue.csv"
    if not path.exists():
        return [], list(REVIEW_QUEUE_FIELDS)
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or REVIEW_QUEUE_FIELDS)
    return rows, fieldnames


def read_review_queue_index() -> dict[str, dict[str, str]]:
    rows, _ = read_review_queue_rows()
    items: dict[str, dict[str, str]] = {}
    for row in rows:
        target = str(row.get("target_image_path") or row.get("image") or "")
        image = Path(target).name
        if not image:
            continue
        normalized = dict(row)
        normalized["review_decision"] = normalize_review_decision(row.get("review_decision", "pending"))
        normalized["usable_for_training"] = normalize_tri_state(row.get("usable_for_training", "pending"))
        normalized["usable_for_validation"] = normalize_tri_state(row.get("usable_for_validation", "pending"))
        items[image] = normalized
    return items


def summarize_review_queue() -> dict[str, object]:
    rows, _ = read_review_queue_rows()
    decision_counts = {key: 0 for key in sorted(REVIEW_DECISIONS)}
    boundary_counts: dict[str, int] = {}
    related_counts: dict[str, int] = {}
    for row in rows:
        decision = normalize_review_decision(row.get("review_decision", "pending"))
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        boundary = str(row.get("boundary_category") or "")
        if boundary:
            boundary_counts[boundary] = boundary_counts.get(boundary, 0) + 1
        related = str(row.get("related_failure_case") or "")
        if related:
            related_counts[related] = related_counts.get(related, 0) + 1

    total = len(rows)
    reviewed = total - decision_counts.get("pending", 0)
    ready_for_merge = reviewed == total and decision_counts.get("needs_fix", 0) == 0
    return {
        "batch_id": BATCH_ROOT.name,
        "total_items": total,
        "reviewed_items": reviewed,
        "pending_items": decision_counts.get("pending", 0),
        "decision_counts": decision_counts,
        "boundary_category_counts": boundary_counts,
        "related_failure_case_counts": related_counts,
        "ready_for_merge": ready_for_merge,
    }


def update_review_summary_file() -> None:
    summary = summarize_review_queue()
    summary_path = BATCH_ROOT / "meta" / "review_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_review_seeded() -> None:
    REVIEW_LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_META_DIR.mkdir(parents=True, exist_ok=True)
    for image_path in FRAMES_DIR.iterdir():
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        dst = REVIEW_LABELS_DIR / f"{image_path.stem}.txt"
        if dst.exists():
            continue
        src = DRAFT_LABELS_DIR / f"{image_path.stem}.txt"
        if src.exists():
            shutil.copy2(src, dst)
        else:
            dst.write_text("", encoding="utf-8")


def read_label_status(image: str) -> str:
    status_path = REVIEW_META_DIR / f"{Path(image).stem}.json"
    if not status_path.exists():
        return "draft"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "reviewed"
    return normalize_status(str(payload.get("status") or "draft"))


def read_labels(image: str) -> list[dict[str, float | int]]:
    ensure_review_seeded()
    label_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.txt"
    if not label_path.exists():
        return []
    labels: list[dict[str, float | int]] = []
    for line in label_path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        cls, x, y, w, h = parts
        labels.append(
            {
                "class_id": int(float(cls)),
                "x": float(x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
            }
        )
    return labels


def write_labels(image: str, labels: list[object], status: str) -> None:
    if not (FRAMES_DIR / image).exists():
        raise FileNotFoundError(image)
    REVIEW_LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_META_DIR.mkdir(parents=True, exist_ok=True)
    class_count = len(read_label_classes())
    lines = []
    for raw in labels:
        if not isinstance(raw, dict):
            continue
        cls = int(raw["class_id"])
        if cls < 0 or cls >= class_count:
            continue
        x = clamp(float(raw["x"]))
        y = clamp(float(raw["y"]))
        w = clamp(float(raw["w"]))
        h = clamp(float(raw["h"]))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{cls} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
    label_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.txt"
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    existing_meta: dict[str, object] = {}
    meta_path = REVIEW_META_DIR / f"{Path(image).stem}.json"
    if meta_path.exists():
        try:
            existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_meta = {}
    review_row = read_review_queue_index().get(image, {})
    existing_meta.update(
        {
            "image": image,
            "status": normalize_status(status),
            "label_count": len(lines),
            "review_decision": review_row.get("review_decision", "pending"),
            "correct_class": review_row.get("correct_class", ""),
            "usable_for_training": review_row.get("usable_for_training", "pending"),
            "usable_for_validation": review_row.get("usable_for_validation", "pending"),
            "reject_reason": review_row.get("reject_reason", ""),
            "review_notes": review_row.get("review_notes", ""),
        }
    )
    meta_path.write_text(json.dumps(existing_meta, ensure_ascii=False, indent=2), encoding="utf-8")


def update_review_row(
    *,
    image: str,
    review_decision: str,
    correct_class: str,
    usable_for_training: str,
    usable_for_validation: str,
    reject_reason: str,
    review_notes: str,
) -> dict[str, str]:
    rows, fieldnames = read_review_queue_rows()
    queue_path = BATCH_ROOT / "meta" / "review_queue.csv"
    if not rows:
        raise FileNotFoundError(f"review_queue not found: {queue_path}")

    decision = normalize_review_decision(review_decision)
    train_flag = normalize_tri_state(usable_for_training)
    val_flag = normalize_tri_state(usable_for_validation)

    if decision == "pass_train":
        train_flag = "true"
        val_flag = "false"
    elif decision == "pass_val":
        train_flag = "false"
        val_flag = "true"
    elif decision == "reject":
        train_flag = "false"
        val_flag = "false"
    elif decision == "needs_fix":
        train_flag = "pending"
        val_flag = "pending"

    label_classes = read_label_classes()
    if correct_class and correct_class not in label_classes and correct_class not in REVIEW_CLASS_DISPLAY_ORDER:
        correct_class = ""

    updated_row: dict[str, str] | None = None
    for row in rows:
        target_image = Path(str(row.get("target_image_path") or row.get("image") or "")).name
        if target_image != image:
            continue
        row["review_decision"] = decision
        row["correct_class"] = correct_class
        row["usable_for_training"] = train_flag
        row["usable_for_validation"] = val_flag
        row["reject_reason"] = reject_reason
        row["review_notes"] = review_notes
        if not row.get("current_class"):
            row["current_class"] = infer_current_class_name(image)
        updated_row = dict(row)
        break

    if updated_row is None:
        raise FileNotFoundError(f"review row not found for image: {image}")

    fieldnames = merge_fieldnames(fieldnames, REVIEW_QUEUE_FIELDS)
    with queue_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    meta_path = REVIEW_META_DIR / f"{Path(image).stem}.json"
    meta_payload: dict[str, object] = {}
    if meta_path.exists():
        try:
            meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta_payload = {}
    meta_payload.update(
        {
            "image": image,
            "status": "reviewed" if decision != "pending" else "draft",
            "review_decision": decision,
            "correct_class": correct_class,
            "usable_for_training": train_flag,
            "usable_for_validation": val_flag,
            "reject_reason": reject_reason,
            "review_notes": review_notes,
            "label_count": len(read_labels(image)),
        }
    )
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    update_review_summary_file()
    return updated_row


def merge_fieldnames(original: list[str], required: list[str]) -> list[str]:
    merged = list(original)
    for name in required:
        if name not in merged:
            merged.append(name)
    return merged


def infer_current_class_name(image: str) -> str:
    labels = read_labels(image)
    label_classes = read_label_classes()
    if not labels:
        return ""
    class_id = labels[0]["class_id"]
    if isinstance(class_id, int) and 0 <= class_id < len(label_classes):
        return label_classes[class_id]
    return ""


def normalize_review_decision(value: object) -> str:
    text = str(value or "pending").strip()
    return text if text in REVIEW_DECISIONS else "pending"


def normalize_tri_state(value: object) -> str:
    text = str(value or "pending").strip().lower()
    return text if text in TRI_STATE else "pending"


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--batch-id", default="batch_001")
    args = parser.parse_args()

    configure_batch(args.batch_id)
    ensure_review_seeded()
    update_review_summary_file()
    server = ThreadingHTTPServer((args.host, args.port), FallHintLabelerHandler)
    print(f"Fall hint labeler running at http://{args.host}:{args.port}")
    print(f"Batch root: {BATCH_ROOT}")
    print(f"Review labels will be saved to {REVIEW_LABELS_DIR}")
    server.serve_forever()
    return 0


def configure_batch(batch_id: str) -> None:
    global BATCH_ROOT, FRAMES_DIR, DRAFT_LABELS_DIR, REVIEW_LABELS_DIR, REVIEW_META_DIR
    BATCH_ROOT = ROOT / "datasets" / "fall_hint_v2_raw" / batch_id
    FRAMES_DIR = BATCH_ROOT / "frames"
    DRAFT_LABELS_DIR = BATCH_ROOT / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    REVIEW_LABELS_DIR = BATCH_ROOT / "human_review" / "labels"
    REVIEW_META_DIR = BATCH_ROOT / "human_review" / "meta"
    if not FRAMES_DIR.exists():
        raise SystemExit(f"Batch frames not found: {FRAMES_DIR}")


if __name__ == "__main__":
    raise SystemExit(main())
