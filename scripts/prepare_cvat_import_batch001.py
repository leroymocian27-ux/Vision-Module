from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


ROOT = Path(r"D:/Program/vision_service/datasets/fall_hint_v2_raw/batch_001")
FRAMES_DIR = ROOT / "frames"
PRELABEL_DIR = ROOT / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
OUT_DIR = ROOT / "cvat_yolo_import"
IMG_OUT = OUT_DIR / "train" / "images"
LBL_OUT = OUT_DIR / "train" / "labels"
ZIP_PATH = ROOT / "cvat_yolo_import_batch001.zip"

CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]


def main() -> int:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    IMG_OUT.mkdir(parents=True, exist_ok=True)
    LBL_OUT.mkdir(parents=True, exist_ok=True)

    image_exts = {".jpg", ".jpeg", ".png"}
    images = sorted(path for path in FRAMES_DIR.iterdir() if path.suffix.lower() in image_exts)

    for image_path in images:
        shutil.copy2(image_path, IMG_OUT / image_path.name)
        src_label = PRELABEL_DIR / f"{image_path.stem}.txt"
        dst_label = LBL_OUT / f"{image_path.stem}.txt"
        if src_label.exists():
            shutil.copy2(src_label, dst_label)
        else:
            dst_label.write_text("", encoding="utf-8")

    (OUT_DIR / "data.yaml").write_text(
        "path: .\n"
        "train: train/images\n"
        "\n"
        "names:\n"
        + "\n".join(f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES))
        + "\n",
        encoding="utf-8",
    )

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in OUT_DIR.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(OUT_DIR))

    print(f"[OK] images={len(images)}")
    print(f"[OK] output={ZIP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
