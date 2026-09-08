"""课堂演示：读取一个图片文件夹，生成增强图片并保存。"""

# 第 1 步：导入需要的库
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import albumentations as A
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# 支持的图片格式
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


#定义数据增强方法
def build_augmentation():

    # 水平翻转
    hf = A.HorizontalFlip(p=0.5)

    # 改变亮度、对比度
    bc = A.RandomBrightnessContrast(
        brightness_limit=0.20,
        contrast_limit=0.20,
        p=0.5,
    )

    # 模拟模糊
    mb = A.MotionBlur(blur_limit=(3, 7), p=0.25)
    gb = A.GaussianBlur(blur_limit=(3, 5), p=0.15)

    # 缩放、平移、旋转、剪切
    af = A.Affine(
        scale=(0.95, 1.05),
        translate_percent=(-0.03, 0.03),
        rotate=(-8, 8),
        shear=(-2, 2),
        border_mode=cv2.BORDER_REFLECT_101,
        p=0.3,
    )

    


    # 6. 将前面的增强方法按顺序放入列表
    operations = [
        hf,
        bc,
        mb,
        gb,
        af,
    ]

    # 7. 使用 Compose 组合成完整的数据增强流程
    augmentation = A.Compose(operations)

    return augmentation


# 第 3 步：接入图片文件夹
def augment_folder(input_dir, output_dir, copies=3, seed=42, overwrite=False):
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"输入文件夹不存在：{input_dir}")
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("输出文件夹不能位于输入文件夹内部。")
    if copies < 1:
        raise ValueError("每张图片的增强数量至少为 1。")

    # rglob 会递归读取输入文件夹及其所有子文件夹
    image_paths = [
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_TYPES
    ]
    image_paths.sort()

    if not image_paths:
        raise FileNotFoundError("输入文件夹中没有找到图片。")

    augmentation = build_augmentation()
    generated = 0

    # 第 4 步：逐张读取、增强并保存
    for image_index, image_path in enumerate(image_paths):
        # PIL 可以直接处理包含中文字符的 Windows 路径
        with Image.open(image_path) as image:
            image = np.array(image.convert("RGB"))

        # 保留输入文件夹原有的类别/子目录结构
        relative_folder = image_path.relative_to(input_dir).parent
        save_folder = output_dir / relative_folder
        save_folder.mkdir(parents=True, exist_ok=True)

        for copy_index in range(1, copies + 1):
            # 固定随机种子，保证课堂演示可以复现
            current_seed = seed + image_index * copies + copy_index
            augmentation.set_random_seed(current_seed)

            augmented_image = augmentation(image=image)["image"]
            save_path = save_folder / (
                f"{image_path.stem}_aug_{copy_index:02d}{image_path.suffix.lower()}"
            )

            if save_path.exists() and not overwrite:
                raise FileExistsError(f"文件已存在，拒绝覆盖：{save_path}")

            Image.fromarray(augmented_image).save(save_path)
            generated += 1
            print(f"已生成：{save_path}")

    print(f"\n处理完成：{len(image_paths)} 张原图，共生成 {generated} 张增强图。")
    return generated


def create_preview(input_dir, output_dir, copy_index=1, max_pairs=2):
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()

    image_paths = [
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_TYPES
    ]
    image_paths.sort()

    pairs = []
    for image_path in image_paths:
        relative_folder = image_path.relative_to(input_dir).parent
        augmented_path = output_dir / relative_folder / (
            f"{image_path.stem}_aug_{copy_index:02d}{image_path.suffix.lower()}"
        )
        if augmented_path.is_file():
            pairs.append((image_path, augmented_path))
        if len(pairs) >= max_pairs:
            break

    if not pairs:
        print("未找到可预览的增强图片，跳过预览图生成。")
        return None

    canvas_w, canvas_h = 1920, 1080
    pad = 24
    grid_gap = 26
    image_gap = 20
    label_h = 32
    grid_cols = 1
    grid_rows = (len(pairs) + grid_cols - 1) // grid_cols
    pair_w = (canvas_w - pad * 2 - grid_gap * (grid_cols - 1)) // grid_cols
    pair_h = (canvas_h - pad * 2 - grid_gap * (grid_rows - 1)) // grid_rows
    thumb_w = (pair_w - image_gap) // 2
    thumb_h = min(pair_h - label_h, int(thumb_w * 9 / 16))
    content_h = grid_rows * (label_h + thumb_h) + grid_gap * (grid_rows - 1)
    start_y = (canvas_h - content_h) // 2
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    def load_font(size):
        for font_path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(font_path, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    label_font = load_font(22)

    for index, (original_path, augmented_path) in enumerate(pairs):
        row = index // grid_cols
        pair_col = index % grid_cols
        pair_x = pad + pair_col * (pair_w + grid_gap)
        pair_y = start_y + row * (label_h + thumb_h + grid_gap)
        columns = [("Original", original_path), ("Augmented", augmented_path)]
        for col, (label, image_path) in enumerate(columns):
            image = Image.open(image_path).convert("RGB")
            image.thumbnail((thumb_w, thumb_h))

            x = pair_x + col * (thumb_w + image_gap)
            draw.text(
                (x, pair_y),
                f"{label}: {image_path.parent.name}/{image_path.name}",
                fill=(20, 20, 20),
                font=label_font,
            )

            frame = Image.new("RGB", (thumb_w, thumb_h), "white")
            frame.paste(
                image,
                ((thumb_w - image.width) // 2, (thumb_h - image.height) // 2),
            )
            canvas.paste(frame, (x, pair_y + label_h))

    preview_path = output_dir / "augmentation_preview.jpg"
    canvas.save(preview_path, quality=92)
    print(f"效果预览图：{preview_path}")
    return preview_path


def create_single_image_effect_preview(
    input_dir,
    output_dir,
    seed=42,
    open_original=False,
    wait_seconds=1.5,
):
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    image_paths = [
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_TYPES
    ]
    image_paths.sort()

    if not image_paths:
        raise FileNotFoundError("输入文件夹中没有找到图片。")

    original_path = image_paths[0]
    if open_original:
        print(f"原始图片：{original_path}")
        open_preview_image(original_path, zoom_steps=1)
        print(f"等待 {wait_seconds} 秒后展示增强效果。\n")
        time.sleep(wait_seconds)

    with Image.open(original_path) as image:
        original_image = np.array(image.convert("RGB"))

    effects = [
        (
            "水平翻转",
            "flip",
            A.HorizontalFlip(p=1.0),
        ),
        (
            "轻微旋转",
            "rotate",
            A.Affine(
                rotate=(8, 8),
                border_mode=cv2.BORDER_REFLECT_101,
                p=1.0,
            ),
        ),
        (
            "亮度对比度",
            "light",
            A.RandomBrightnessContrast(
                brightness_limit=(0.18, 0.18),
                contrast_limit=(0.18, 0.18),
                p=1.0,
            ),
        ),
        (
            "运动模糊",
            "motion_blur",
            A.MotionBlur(blur_limit=(7, 7), p=1.0),
        ),
    ]

    gallery_items = []
    generated = 0
    for effect_index, (label, suffix, transform) in enumerate(effects, start=1):
        transform.set_random_seed(seed + effect_index)
        augmented_image = transform(image=original_image)["image"]
        save_path = output_dir / f"{original_path.stem}_{suffix}{original_path.suffix.lower()}"
        Image.fromarray(augmented_image).save(save_path)
        gallery_items.append((label, save_path))
        generated += 1
        print(f"已生成 {label} 效果：{save_path}")

    preview_path = output_dir / "augmentation_preview.jpg"
    save_effect_gallery(gallery_items, preview_path)
    print(f"\n处理完成：1 张原图，共生成 {generated} 张单项增强图。")
    print(f"效果预览图：{preview_path}")
    return preview_path


def save_effect_gallery(items, preview_path):
    canvas_w, canvas_h = 1920, 1080
    pad = 24
    gap_x = 28
    gap_y = 24
    label_h = 40
    cols = 2
    rows = (len(items) + cols - 1) // cols
    cell_w = (canvas_w - pad * 2 - gap_x * (cols - 1)) // cols
    cell_h = (canvas_h - pad * 2 - gap_y * (rows - 1)) // rows
    image_h = cell_h - label_h
    cell_h = label_h + image_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    label_font = load_preview_font(28)

    for index, (label, image_path) in enumerate(items):
        row = index // cols
        col = index % cols
        x = pad + col * (cell_w + gap_x)
        y = pad + row * (cell_h + gap_y)
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            image.thumbnail((cell_w, image_h))

        draw.text((x, y), label, fill=(20, 20, 20), font=label_font)
        paste_x = x + (cell_w - image.width) // 2
        paste_y = y + label_h + (image_h - image.height) // 2
        canvas.paste(image, (paste_x, paste_y))

    canvas.save(preview_path, quality=92)


def load_preview_font(size):
    for font_path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def open_preview_image(preview_path, zoom_steps=2):
    if preview_path is None:
        return

    preview_path = Path(preview_path).resolve()
    if os.name == "nt":
        try:
            photo_uri = "ms-photos:viewer?fileName=" + quote(str(preview_path))
            os.startfile(photo_uri)
            print(f"已使用 Windows 照片打开效果图：{preview_path}")
            zoom_preview_image(zoom_steps=zoom_steps)
            return
        except OSError:
            pass

    try:
        os.startfile(preview_path)
        print(f"已自动打开效果图：{preview_path}")
    except OSError as exc:
        print(f"自动打开效果图失败，请手动打开：{preview_path}")
        print(f"失败原因：{exc}")


def zoom_preview_image(zoom_steps=2):
    if os.name != "nt" or zoom_steps < 1:
        return

    time.sleep(1.2)
    zoom_commands = []
    for _ in range(zoom_steps):
        zoom_commands.append("[System.Windows.Forms.SendKeys]::SendWait('^{ADD}')")
        zoom_commands.append("Start-Sleep -Milliseconds 120")

    powershell_script = "; ".join(
        ["Add-Type -AssemblyName System.Windows.Forms", *zoom_commands]
    )
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            powershell_script,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print(f"已自动放大效果图：{zoom_steps} 次")


def reset_demo_output(output_dir, default_output):
    output_dir = Path(output_dir).resolve()
    default_output = Path(default_output).resolve()

    if output_dir != default_output:
        return
    if output_dir.exists():
        shutil.rmtree(output_dir)
        print(f"已清理旧演示输出：{output_dir}")


# 第 5 步：通过命令行传入图片文件夹
def main():
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[1]
    default_input = project_root.parent / "data"
    default_output = project_root / "data" / "augment_image_folder_demo"
    direct_run = len(sys.argv) == 1

    parser = argparse.ArgumentParser(description="批量生成数据增强图片")
    parser.add_argument(
        "--input",
        default=str(default_input),
        help=f"原始图片文件夹，默认：{default_input}",
    )
    parser.add_argument(
        "--output",
        default=str(default_output),
        help=f"增强图片输出文件夹，默认：{default_output}",
    )
    parser.add_argument("--copies", type=int, default=1, help="每张原图生成几张增强图")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=direct_run,
        help="如果输出图片已存在，则直接覆盖，方便课堂演示重复运行",
    )
    parser.add_argument(
        "--no-overwrite",
        dest="overwrite",
        action="store_false",
        help="输出图片已存在时拒绝覆盖",
    )
    parser.add_argument(
        "--preview",
        dest="preview",
        action="store_true",
        default=True,
        help="生成原图和增强图对比预览",
    )
    parser.add_argument(
        "--no-preview",
        dest="preview",
        action="store_false",
        help="不生成对比预览图",
    )
    parser.add_argument(
        "--open-preview",
        dest="open_preview",
        action="store_true",
        default=direct_run,
        help="生成预览图后自动打开图片",
    )
    parser.add_argument(
        "--no-open-preview",
        dest="open_preview",
        action="store_false",
        help="生成预览图后不自动打开图片",
    )
    args = parser.parse_args()

    if direct_run:
        print("未传入命令行参数，使用默认演示配置。")
        print(f"输入文件夹：{args.input}")
        print(f"输出文件夹：{args.output}")
        print("演示模式：只选择 1 张原图，生成 4 张单项增强效果图。")
        print("已启用覆盖旧输出，方便在 VS Code 中重复点击运行。\n")
        reset_demo_output(args.output, default_output)
        preview_path = create_single_image_effect_preview(
            input_dir=args.input,
            output_dir=args.output,
            seed=args.seed,
            open_original=args.open_preview,
        )
        if args.open_preview:
            open_preview_image(preview_path)
        return

    augment_folder(
        input_dir=args.input,
        output_dir=args.output,
        copies=args.copies,
        seed=args.seed,
        overwrite=args.overwrite,
    )

    if args.preview:
        preview_path = create_preview(
            input_dir=args.input,
            output_dir=args.output,
            copy_index=1,
        )
        if args.open_preview:
            open_preview_image(preview_path)


if __name__ == "__main__":
    main()
