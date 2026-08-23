from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


DATASET = Path(r"D:/Program/vision_service/datasets/fall_hint_v2")
CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def main() -> int:
    errors: list[str] = []
    stats = defaultdict(Counter)

    for split in ["train", "val", "test"]:
        image_dir = DATASET / "images" / split
        label_dir = DATASET / "labels" / split
        if not image_dir.exists():
            errors.append(f"[MISSING_DIR] {image_dir}")
            continue
        if not label_dir.exists():
            errors.append(f"[MISSING_DIR] {label_dir}")
            continue

        images = sorted(path for path in image_dir.glob("*") if path.suffix.lower() in IMAGE_EXTS)
        for image_path in images:
            label_path = label_dir / f"{image_path.stem}.txt"
            if not label_path.exists():
                errors.append(f"[MISSING_LABEL] {split}: {image_path.name}")
                continue

            text = label_path.read_text(encoding="utf-8").strip()
            if text == "":
                stats[split]["empty_no_person"] += 1
                continue

            for line_index, line in enumerate(text.splitlines(), start=1):
                parts = line.strip().split()
                if len(parts) != 5:
                    errors.append(f"[BAD_COLS] {split}: {label_path.name}:{line_index} -> {line}")
                    continue

                try:
                    cls = int(float(parts[0]))
                    x_center, y_center, width, height = map(float, parts[1:])
                except ValueError:
                    errors.append(f"[BAD_VALUE] {split}: {label_path.name}:{line_index} -> {line}")
                    continue

                if cls not in CLASS_NAMES:
                    errors.append(f"[BAD_CLASS] {split}: {label_path.name}:{line_index} cls={cls}")
                if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
                    errors.append(f"[BAD_BOX] {split}: {label_path.name}:{line_index} -> {line}")

                stats[split][CLASS_NAMES.get(cls, f"unknown_{cls}")] += 1
                stats[split]["total_boxes"] += 1

        stats[split]["total_images"] = len(images)

    print("========== DATASET STATS ==========")
    for split in ["train", "val", "test"]:
        print(f"\n[{split}]")
        for key, value in stats[split].items():
            print(f"{key}: {value}")

    print("\n========== ERRORS ==========")
    if errors:
        for error in errors[:200]:
            print(error)
        print(f"\nTOTAL ERRORS: {len(errors)}")
        return 1

    print("PASS: no format errors found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
