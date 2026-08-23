from __future__ import annotations

import csv
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = ROOT / "datasets" / "pose_yolo_raw"
STATIC_DIR = Path(__file__).resolve().parent / "static"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

BATCH_ROOT: Path
FRAMES_DIR: Path
PRELABELS_DIR: Path
REVIEW_LABELS_DIR: Path
REVIEW_META_DIR: Path


class PoseLabelerHandler(BaseHTTPRequestHandler):
    server_version = "PoseLabeler/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/batch":
            self._send_json({"batch_id": BATCH_ROOT.name, "keypoints": KEYPOINT_NAMES})
            return
        if parsed.path == "/api/images":
            self._send_json({"images": list_images()})
            return
        if parsed.path == "/api/label":
            query = parse_qs(parsed.query)
            image = safe_name(query.get("image", [""])[0])
            self._send_json(read_label(image))
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
        annotations = payload.get("annotations")
        if not isinstance(annotations, list):
            self.send_error(400, "annotations must be a list")
            return
        write_label(image, annotations, status=str(payload.get("status") or "reviewed"))
        self._send_json({"ok": True})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[pose-labeler] {self.address_string()} - {fmt % args}")

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
    frame_meta = read_frame_manifest()
    images = sorted(path.name for path in FRAMES_DIR.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    items = []
    for image in images:
        meta = frame_meta.get(image, {})
        status = "draft"
        review_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.json"
        if review_path.exists():
            try:
                status = str(json.loads(review_path.read_text(encoding="utf-8")).get("status") or "reviewed")
            except json.JSONDecodeError:
                status = "reviewed"
        items.append(
            {
                "image": image,
                "status": status,
                "group": meta.get("group", ""),
                "scene": meta.get("scene", ""),
                "source_dataset": meta.get("source_dataset", ""),
                "video_id": meta.get("video_id", ""),
                "person_boxes": meta.get("person_boxes", ""),
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


def read_label(image: str) -> dict[str, object]:
    review_path = REVIEW_LABELS_DIR / f"{Path(image).stem}.json"
    if review_path.exists():
        return json.loads(review_path.read_text(encoding="utf-8"))
    prelabel_path = PRELABELS_DIR / f"{Path(image).stem}.json"
    if prelabel_path.exists():
        payload = json.loads(prelabel_path.read_text(encoding="utf-8"))
        payload["status"] = "draft"
        return payload
    return {"image": image, "status": "draft", "annotations": []}


def write_label(image: str, annotations: list[object], status: str) -> None:
    if not (FRAMES_DIR / image).exists():
        raise FileNotFoundError(image)
    cleaned = []
    for raw in annotations:
        if not isinstance(raw, dict):
            continue
        bbox = clean_bbox(raw.get("bbox"))
        keypoints = clean_keypoints(raw.get("keypoints"))
        cleaned.append({"bbox": bbox, "keypoints": keypoints})
    REVIEW_LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_META_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"image": image, "status": status, "annotations": cleaned}
    (REVIEW_LABELS_DIR / f"{Path(image).stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    visible = sum(1 for ann in cleaned for kp in ann["keypoints"] if int(kp["v"]) > 0)
    (REVIEW_META_DIR / f"{Path(image).stem}.json").write_text(
        json.dumps(
            {
                "image": image,
                "status": status,
                "person_count": len(cleaned),
                "visible_keypoint_count": visible,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clean_bbox(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}
    x = clamp(float(value.get("x", 0.5)))
    y = clamp(float(value.get("y", 0.5)))
    w = clamp(float(value.get("w", 0.1)))
    h = clamp(float(value.get("h", 0.1)))
    return {"x": x, "y": y, "w": max(0.0, w), "h": max(0.0, h)}


def clean_keypoints(value: object) -> list[dict[str, float | int | str]]:
    by_name = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                by_name[str(item.get("name") or "")] = item
    keypoints = []
    for name in KEYPOINT_NAMES:
        raw = by_name.get(name, {})
        v = int(raw.get("v", 0)) if isinstance(raw, dict) else 0
        keypoints.append(
            {
                "name": name,
                "x": clamp(float(raw.get("x", 0.0))) if isinstance(raw, dict) else 0.0,
                "y": clamp(float(raw.get("y", 0.0))) if isinstance(raw, dict) else 0.0,
                "v": 2 if v >= 2 else (1 if v == 1 else 0),
            }
        )
    return keypoints


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def configure_batch(batch_id: str) -> None:
    global BATCH_ROOT, FRAMES_DIR, PRELABELS_DIR, REVIEW_LABELS_DIR, REVIEW_META_DIR
    BATCH_ROOT = RAW_ROOT / batch_id
    FRAMES_DIR = BATCH_ROOT / "frames"
    PRELABELS_DIR = BATCH_ROOT / "prelabels"
    REVIEW_LABELS_DIR = BATCH_ROOT / "human_review" / "labels"
    REVIEW_META_DIR = BATCH_ROOT / "human_review" / "meta"
    if not FRAMES_DIR.exists():
        raise SystemExit(f"Batch frames not found: {FRAMES_DIR}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--batch-id", default="batch_001")
    args = parser.parse_args()

    configure_batch(args.batch_id)
    REVIEW_LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_META_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), PoseLabelerHandler)
    print(f"Pose labeler running at http://{args.host}:{args.port}")
    print(f"Review labels will be saved to {REVIEW_LABELS_DIR}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
