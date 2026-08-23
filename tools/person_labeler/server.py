from __future__ import annotations

import csv
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = ROOT / "datasets" / "person_yolo_raw"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CLASSES = ["person"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

BATCH_ROOT: Path
FRAMES_DIR: Path
REVIEW_LABELS_DIR: Path
REVIEW_META_DIR: Path


class PersonLabelerHandler(BaseHTTPRequestHandler):
    server_version = "PersonLabeler/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/classes":
            self._send_json({"classes": CLASSES})
            return
        if parsed.path == "/api/batch":
            self._send_json({"batch_id": BATCH_ROOT.name})
            return
        if parsed.path == "/api/images":
            self._send_json({"images": list_images()})
            return
        if parsed.path == "/api/label":
            query = parse_qs(parsed.query)
            image = safe_name(query.get("image", [""])[0])
            self._send_json({"image": image, "labels": read_labels(image)})
            return
        if parsed.path.startswith("/frames/"):
            image = safe_name(unquote(parsed.path.removeprefix("/frames/")))
            self._send_file(FRAMES_DIR / image, mimetypes.guess_type(image)[0] or "application/octet-stream")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/label":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        image = safe_name(str(payload.get("image") or ""))
        labels = payload.get("labels")
        if not isinstance(labels, list):
            self.send_error(400, "labels must be a list")
            return
        write_labels(image, labels, status=str(payload.get("status") or "reviewed"))
        self._send_json({"ok": True})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[person-labeler] {self.address_string()} - {fmt % args}")

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


def list_images() -> list[dict[str, object]]:
    ensure_review_seeded()
    frame_meta = read_frame_manifest()
    images = sorted(path.name for path in FRAMES_DIR.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    items = []
    for image in images:
        meta = frame_meta.get(image, {})
        label_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.txt"
        meta_path = REVIEW_META_DIR / f"{Path(image).stem}.json"
        status = "draft"
        if meta_path.exists():
            try:
                status = str(json.loads(meta_path.read_text(encoding="utf-8")).get("status") or "reviewed")
            except json.JSONDecodeError:
                status = "reviewed"
        items.append(
            {
                "image": image,
                "status": status,
                "has_label": label_path.exists() and label_path.read_text(encoding="utf-8").strip() != "",
                "video_id": meta.get("video_id", ""),
                "scene": meta.get("scene", ""),
                "group": meta.get("group", ""),
                "source_dataset": meta.get("source_dataset", ""),
                "note": meta.get("note", ""),
            }
        )
    return items


def read_frame_manifest() -> dict[str, dict[str, str]]:
    path = BATCH_ROOT / "meta" / "frame_manifest.csv"
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def ensure_review_seeded() -> None:
    REVIEW_LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_META_DIR.mkdir(parents=True, exist_ok=True)
    for image_path in FRAMES_DIR.iterdir():
        if image_path.suffix.lower() not in IMAGE_EXTS:
            continue
        label_path = REVIEW_LABELS_DIR / f"{image_path.stem}.txt"
        if not label_path.exists():
            label_path.write_text("", encoding="utf-8")


def read_labels(image: str) -> list[dict[str, float | int]]:
    ensure_review_seeded()
    label_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.txt"
    labels = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        cls, x, y, w, h = parts
        labels.append({"class_id": int(float(cls)), "x": float(x), "y": float(y), "w": float(w), "h": float(h)})
    return labels


def write_labels(image: str, labels: list[object], status: str) -> None:
    if not (FRAMES_DIR / image).exists():
        raise FileNotFoundError(image)
    lines = []
    for raw in labels:
        if not isinstance(raw, dict):
            continue
        x = clamp(float(raw["x"]))
        y = clamp(float(raw["y"]))
        w = clamp(float(raw["w"]))
        h = clamp(float(raw["h"]))
        if w <= 0 or h <= 0:
            continue
        lines.append(f"0 {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
    (REVIEW_LABELS_DIR / f"{Path(image).stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (REVIEW_META_DIR / f"{Path(image).stem}.json").write_text(
        json.dumps({"image": image, "status": status, "label_count": len(lines)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def configure_batch(batch_id: str) -> None:
    global BATCH_ROOT, FRAMES_DIR, REVIEW_LABELS_DIR, REVIEW_META_DIR
    BATCH_ROOT = RAW_ROOT / batch_id
    FRAMES_DIR = BATCH_ROOT / "frames"
    REVIEW_LABELS_DIR = BATCH_ROOT / "human_review" / "labels"
    REVIEW_META_DIR = BATCH_ROOT / "human_review" / "meta"
    if not FRAMES_DIR.exists():
        raise SystemExit(f"Batch frames not found: {FRAMES_DIR}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--batch-id", default="batch_001")
    args = parser.parse_args()

    configure_batch(args.batch_id)
    ensure_review_seeded()
    server = ThreadingHTTPServer((args.host, args.port), PersonLabelerHandler)
    print(f"Person labeler running at http://{args.host}:{args.port}")
    print(f"Review labels will be saved to {REVIEW_LABELS_DIR}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
