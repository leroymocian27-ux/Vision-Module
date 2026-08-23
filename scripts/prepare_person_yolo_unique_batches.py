from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
PERSON_RAW = ROOT / "datasets" / "person_yolo_raw"
FALL_HINT_RAW = ROOT / "datasets" / "fall_hint_v2_raw"
FINAL_ROOT = ROOT / "datasets" / "person_yolo"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class Candidate:
    image_path: Path
    image_name: str
    source_batch: str
    source_dataset: str
    source_video: str
    source_frame_index: str
    timestamp_ms: str
    source_scene: str
    source_group: str
    license: str
    person_group: str
    person_scene: str
    note: str


BATCH_TARGETS: dict[str, dict[str, int]] = {
    "batch_003": {
        "falling": 22,
        "fallen": 12,
        "lying": 18,
        "kneeling": 14,
        "bending": 12,
        "sitting": 8,
        "standing": 8,
        "no_person": 4,
        "hard_negative_object": 21,
        "multi_occlusion_complex": 1,
    },
    "batch_004": {
        "falling": 24,
        "fallen": 10,
        "lying": 24,
        "kneeling": 16,
        "bending": 12,
        "sitting": 8,
        "standing": 6,
        "walking": 6,
        "hard_negative_object": 14,
    },
    "batch_005": {
        "falling": 18,
        "fallen": 12,
        "lying": 22,
        "kneeling": 18,
        "bending": 10,
        "sitting": 8,
        "walking": 6,
        "no_person": 4,
        "hard_negative_object": 22,
    },
    "batch_006": {
        "falling": 26,
        "fallen": 10,
        "lying": 20,
        "kneeling": 16,
        "bending": 12,
        "sitting": 8,
        "standing": 6,
        "hard_negative_object": 22,
    },
    "batch_007": {
        "falling": 24,
        "fallen": 12,
        "lying": 24,
        "kneeling": 16,
        "bending": 10,
        "sitting": 2,
        "walking": 6,
        "hard_negative_object": 26,
    },
    "batch_008": {
        "falling": 31,
        "fallen": 10,
        "lying": 22,
        "kneeling": 22,
        "bending": 10,
        "standing": 6,
        "hard_negative_object": 19,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare globally de-duplicated person YOLO batches.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--batch-id", action="append", choices=sorted(BATCH_TARGETS))
    args = parser.parse_args()

    batch_ids = args.batch_id or sorted(BATCH_TARGETS)
    used_hashes = collect_existing_hashes(exclude_batches=set(batch_ids))
    pools = build_candidate_pools()
    for batch_id in batch_ids:
        prepare_batch(batch_id, BATCH_TARGETS[batch_id], pools, used_hashes, overwrite=args.overwrite)
    return 0


def collect_existing_hashes(*, exclude_batches: set[str]) -> set[str]:
    hashes: set[str] = set()
    for batch_dir in sorted(PERSON_RAW.glob("batch_*")):
        if batch_dir.name in exclude_batches:
            continue
        frames_dir = batch_dir / "frames"
        if not frames_dir.exists():
            continue
        for path in frames_dir.iterdir():
            if path.suffix.lower() in IMAGE_EXTS:
                hashes.add(sha256(path))
    return hashes


def build_candidate_pools() -> dict[str, list[Candidate]]:
    pools: dict[str, list[Candidate]] = defaultdict(list)
    for batch_dir in sorted(FALL_HINT_RAW.glob("batch_*")):
        manifest_path = batch_dir / "meta" / "frame_manifest.csv"
        frames_dir = batch_dir / "frames"
        if not manifest_path.exists() or not frames_dir.exists():
            continue
        with manifest_path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                image_name = row.get("image", "")
                image_path = frames_dir / image_name
                if not image_name or not image_path.exists():
                    continue
                for person_group, note in person_groups_for_row(row):
                    pools[person_group].append(
                        Candidate(
                            image_path=image_path,
                            image_name=image_name,
                            source_batch=batch_dir.name,
                            source_dataset=row.get("source_dataset", ""),
                            source_video=row.get("source_video", ""),
                            source_frame_index=row.get("source_frame_index", ""),
                            timestamp_ms=row.get("timestamp_ms", ""),
                            source_scene=row.get("scene", ""),
                            source_group=row.get("group", ""),
                            license=row.get("license", ""),
                            person_group=person_group,
                            person_scene=scene_for_group(person_group),
                            note=note,
                        )
                    )

    pools["multi_occlusion_complex"].extend(video_candidates(
        video_path=ROOT / "tests" / "fixtures" / "person_bus_loop.mp4",
        video_id="fixture_person_bus_loop",
        group="multi_occlusion_complex",
        scene="multi_person_complex_background",
        count=18,
        source_dataset="test_fixture",
        license_name="project_fixture",
        note="multi-person/complex background; short loop, use sparingly",
    ))
    pools["no_person"].extend(video_candidates(
        video_path=ROOT / "datasets" / "new_pose_raw" / "camera_01" / "session_20260621_160100_no_person" / "video.mp4",
        video_id="local_no_person_clean",
        group="no_person",
        scene="no_person",
        count=8,
        source_dataset="new_pose_raw",
        license_name="local_project_data",
        note="clean empty room negative; limited because static scene duplicates easily",
        start_ratio=0.0,
        end_ratio=0.03,
    ))
    return {group: stable_unique_candidates(values) for group, values in pools.items()}


def person_groups_for_row(row: dict[str, str]) -> list[tuple[str, str]]:
    scene = row.get("scene", "")
    source_dataset = row.get("source_dataset", "")
    items: list[tuple[str, str]] = []
    if scene == "fall":
        items.append(("falling", "fall/fall-transition raw frame; label visible humans as person"))
        items.append(("fallen", "fall sequence frame; use if person is already down/static"))
    elif scene == "fallen_hold":
        items.append(("fallen", "fallen/static raw frame; label visible humans as person"))
    elif scene == "lying":
        items.append(("lying", "lying raw frame; label visible humans as person"))
        items.append(("hard_negative_object", "bed/curtain/furniture-adjacent frame; label visible humans only"))
    elif scene == "kneeling":
        items.append(("kneeling", "kneeling/low-posture raw frame; label visible humans as person"))
    elif scene == "bending":
        items.append(("bending", "bending raw frame; label visible humans as person"))
    elif scene == "sitting":
        items.append(("sitting", "sitting raw frame; label visible humans as person"))
    elif scene == "standing":
        items.append(("standing", "standing raw frame; label visible humans as person"))
    elif scene == "no_person":
        items.append(("no_person", "empty frame; save empty only if no visible human"))

    if source_dataset == "ur_fall" and scene in {"standing", "sitting", "fall"}:
        items.append(("walking", "UR Fall ADL/fall frame may include walking/transition; label visible humans as person"))
    return items


def scene_for_group(group: str) -> str:
    if group == "multi_occlusion_complex":
        return "multi_person_complex_background"
    if group == "hard_negative_object":
        return "hard_negative_object"
    return group


def video_candidates(
    *,
    video_path: Path,
    video_id: str,
    group: str,
    scene: str,
    count: int,
    source_dataset: str,
    license_name: str,
    note: str,
    start_ratio: float = 0.0,
    end_ratio: float = 1.0,
) -> list[Candidate]:
    if not video_path.exists():
        return []
    tmp_dir = PERSON_RAW / "_candidate_cache" / video_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    candidates: list[Candidate] = []
    for out_index, frame_index in enumerate(sample_indices(total, count, start_ratio, end_ratio)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        image_name = f"{video_id}_{out_index:03d}.jpg"
        image_path = tmp_dir / image_name
        cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        candidates.append(
            Candidate(
                image_path=image_path,
                image_name=image_name,
                source_batch="video_extract",
                source_dataset=source_dataset,
                source_video=str(video_path),
                source_frame_index=str(frame_index),
                timestamp_ms=str(int(round((frame_index / fps) * 1000))) if fps > 0 else "",
                source_scene=scene,
                source_group=group,
                license=license_name,
                person_group=group,
                person_scene=scene,
                note=note,
            )
        )
    cap.release()
    return candidates


def prepare_batch(
    batch_id: str,
    targets: dict[str, int],
    pools: dict[str, list[Candidate]],
    used_hashes: set[str],
    *,
    overwrite: bool,
) -> None:
    batch_dir = PERSON_RAW / batch_id
    if batch_dir.exists() and overwrite:
        shutil.rmtree(batch_dir)
    create_structure(batch_dir)
    selected: list[Candidate] = []
    local_hashes: set[str] = set()
    per_source_counts: Counter[str] = Counter()

    for group, count in targets.items():
        picked = pick_candidates(
            pools.get(group, []),
            count=count,
            used_hashes=used_hashes,
            local_hashes=local_hashes,
            per_source_counts=per_source_counts,
        )
        if len(picked) != count:
            raise SystemExit(f"{batch_id}: group {group} needed {count}, got {len(picked)}")
        selected.extend(picked)

    rows = copy_selected(batch_dir, selected, used_hashes)
    write_frame_manifest(batch_dir / "meta" / "frame_manifest.csv", rows)
    write_source_videos(batch_dir / "meta" / "source_videos.csv", selected)
    write_labeling_guide(batch_dir / "meta" / "labeling_guide.md")
    write_data_yaml(FINAL_ROOT / "data.yaml")
    write_summary(batch_dir / "meta" / "prepare_summary.json", batch_id, rows)
    write_preview(batch_dir)
    print(f"[OK] {batch_id}: frames={len(rows)} unique={len({row['sha256'] for row in rows})}")


def pick_candidates(
    candidates: list[Candidate],
    *,
    count: int,
    used_hashes: set[str],
    local_hashes: set[str],
    per_source_counts: Counter[str],
) -> list[Candidate]:
    scored = []
    for index, candidate in enumerate(candidates):
        digest = sha256(candidate.image_path)
        if digest in used_hashes or digest in local_hashes:
            continue
        source_key = f"{candidate.source_batch}:{candidate.source_dataset}:{Path(candidate.source_video).name}"
        scored.append((per_source_counts[source_key], candidate.source_batch, candidate.source_dataset, index, digest, source_key, candidate))
    scored.sort()
    picked: list[Candidate] = []
    for _, _, _, _, digest, source_key, candidate in scored:
        if len(picked) >= count:
            break
        if digest in local_hashes:
            continue
        picked.append(candidate)
        local_hashes.add(digest)
        per_source_counts[source_key] += 1
    return picked


def copy_selected(batch_dir: Path, selected: list[Candidate], used_hashes: set[str]) -> list[dict[str, object]]:
    frames_dir = batch_dir / "frames"
    rows: list[dict[str, object]] = []
    group_index: Counter[str] = Counter()
    for candidate in selected:
        digest = sha256(candidate.image_path)
        group_index[candidate.person_group] += 1
        image_name = f"{batch_dir.name}_{candidate.person_group}_{group_index[candidate.person_group]:03d}{candidate.image_path.suffix.lower()}"
        dst = frames_dir / image_name
        shutil.copy2(candidate.image_path, dst)
        used_hashes.add(digest)
        rows.append(
            {
                "annotation_status": "needs_human_review",
                "group": candidate.person_group,
                "scene": candidate.person_scene,
                "image": image_name,
                "image_path": str(dst.relative_to(ROOT)).replace("\\", "/"),
                "license": candidate.license,
                "source_dataset": candidate.source_dataset,
                "source_batch": candidate.source_batch,
                "source_image": candidate.image_name,
                "source_frame_index": candidate.source_frame_index,
                "source_video": candidate.source_video,
                "start_ratio": "",
                "end_ratio": "",
                "timestamp_ms": candidate.timestamp_ms,
                "video_id": f"{candidate.source_batch}_{Path(candidate.source_video).stem}",
                "note": candidate.note,
                "sha256": digest,
            }
        )
    return rows


def stable_unique_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        digest = sha256(candidate.image_path)
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(candidate)
    return unique


def sample_indices(total: int, count: int, start_ratio: float, end_ratio: float) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    start = max(0, min(total - 1, int(total * start_ratio)))
    end = max(start, min(total - 1, int(total * end_ratio)))
    if count == 1:
        return [(start + end) // 2]
    span = max(1, end - start)
    return [min(total - 1, start + round(span * index / (count - 1))) for index in range(count)]


def create_structure(batch_dir: Path) -> None:
    for path in [batch_dir / "frames", batch_dir / "human_review" / "labels", batch_dir / "human_review" / "meta", batch_dir / "meta"]:
        path.mkdir(parents=True, exist_ok=True)


def write_frame_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "annotation_status",
        "group",
        "scene",
        "image",
        "image_path",
        "license",
        "source_dataset",
        "source_batch",
        "source_image",
        "source_frame_index",
        "source_video",
        "start_ratio",
        "end_ratio",
        "timestamp_ms",
        "video_id",
        "note",
        "sha256",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_source_videos(path: Path, selected: list[Candidate]) -> None:
    rows = {}
    for candidate in selected:
        key = (candidate.source_batch, candidate.source_dataset, candidate.source_video)
        rows[key] = {
            "source_batch": candidate.source_batch,
            "source_dataset": candidate.source_dataset,
            "source_video": candidate.source_video,
            "license": candidate.license,
        }
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["source_batch", "source_dataset", "source_video", "license"])
        writer.writeheader()
        writer.writerows(rows.values())


def write_labeling_guide(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# YOLO person batch labeling guide",
                "",
                "- Class 0 only: person.",
                "- Label every visible human as person.",
                "- Do not label actions such as falling/fallen/sitting/kneeling/bending.",
                "- No-person frames: leave labels empty and save.",
                "- Hard-negative-object frames: label visible humans only; do not box beds, chairs, curtains, cabinets, monitors, shadows, or furniture.",
                "- If a frame contains a tiny/edge/partially visible person, draw a box around the visible body region.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_data_yaml(path: Path) -> None:
    path.write_text(
        "\n".join([f"path: {FINAL_ROOT.as_posix()}", "train: images/train", "val: images/val", "test: images/test", "names:", "  0: person", ""]),
        encoding="utf-8",
    )


def write_summary(path: Path, batch_id: str, rows: list[dict[str, object]]) -> None:
    groups = Counter(str(row["group"]) for row in rows)
    datasets = Counter(str(row["source_dataset"]) for row in rows)
    source_batches = Counter(str(row["source_batch"]) for row in rows)
    payload = {
        "batch_id": batch_id,
        "image_count": len(rows),
        "unique_sha256_count": len({row["sha256"] for row in rows}),
        "groups": dict(sorted(groups.items())),
        "source_datasets": dict(sorted(datasets.items())),
        "source_batches": dict(sorted(source_batches.items())),
        "classes": ["person"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_preview(batch_dir: Path) -> None:
    import numpy as np

    frames = batch_dir / "frames"
    rows = list(csv.DictReader((batch_dir / "meta" / "frame_manifest.csv").open("r", newline="", encoding="utf-8")))
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_group[row["group"]].append(row)
    selected: list[dict[str, str]] = []
    for group in sorted(by_group):
        values = by_group[group]
        picks = [0, len(values) // 2, len(values) - 1] if len(values) >= 3 else list(range(len(values)))
        selected.extend(values[index] for index in picks)
    thumbs = []
    for row in selected:
        img = cv2.imread(str(frames / row["image"]))
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = min(220 / w, 140 / h)
        resized = cv2.resize(img, (int(w * scale), int(h * scale)))
        canvas = np.full((172, 244, 3), 245, dtype=np.uint8)
        x = (244 - resized.shape[1]) // 2
        canvas[: resized.shape[0], x : x + resized.shape[1]] = resized
        label = f"{row['group']} | {row['image'][:24]}"
        cv2.putText(canvas, label, (6, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (20, 20, 20), 1, cv2.LINE_AA)
        thumbs.append(canvas)
    cols = 4
    pad = 8
    sheet_h = ((len(thumbs) + cols - 1) // cols) * (172 + pad) + pad
    sheet_w = cols * (244 + pad) + pad
    sheet = np.full((sheet_h, sheet_w, 3), 230, dtype=np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, cols)
        y = pad + row * (172 + pad)
        x = pad + col * (244 + pad)
        sheet[y : y + 172, x : x + 244] = thumb
    cv2.imwrite(str(batch_dir / "meta" / "preview_contact_sheet.jpg"), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
