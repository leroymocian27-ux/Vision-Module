from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


STYLE = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "white": "\033[97m",
}


def enable_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def styled(text: str, *codes: str) -> str:
    return "".join(codes) + text + STYLE["reset"]


def rule(width: int = 72) -> str:
    return styled("-" * width, STYLE["dim"])


def banner(title: str, subtitle: str | None = None) -> None:
    print()
    print(styled("=" * 72, STYLE["cyan"]))
    print(styled(title, STYLE["bold"], STYLE["cyan"]))
    if subtitle:
        print(styled(subtitle, STYLE["dim"], STYLE["cyan"]))
    print(styled("=" * 72, STYLE["cyan"]))


def section(title: str) -> None:
    print()
    print(styled(f"[SECTION] {title}", STYLE["bold"], STYLE["blue"]))
    print(rule())


def bullet(message: str, *, kind: str = "info") -> None:
    tag = {
        "ok": styled("[OK]", STYLE["green"]),
        "warn": styled("[WARN]", STYLE["yellow"]),
        "error": styled("[ERROR]", STYLE["red"]),
    }.get(kind, styled("[INFO]", STYLE["white"]))
    print(f"  {tag} {message}")


def path_block(label: str, path: str | Path) -> None:
    print(f"  {styled(label + ':', STYLE['dim'])}")
    print(f"    {Path(path)}")


def json_block(label: str, payload: Mapping[str, Any] | list[Any] | str) -> None:
    print(f"  {styled(label + ':', STYLE['dim'])}")
    if isinstance(payload, str):
        print(f"    {payload}")
        return
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for line in text.splitlines():
        print(f"    {line}")


def summary_table(items: list[tuple[str, Any]]) -> None:
    if not items:
        return
    width = max(len(str(key)) for key, _ in items)
    print()
    print(styled("[SUMMARY]", STYLE["bold"], STYLE["blue"]))
    print(rule())
    for key, value in items:
        print(f"  {styled(str(key).ljust(width), STYLE['dim'])}  {value}")


def final_status(title: str, *, color: str = "green", items: list[tuple[str, Any]] | None = None) -> None:
    color_code = {
        "green": STYLE["green"],
        "yellow": STYLE["yellow"],
        "red": STYLE["red"],
        "cyan": STYLE["cyan"],
    }.get(color, STYLE["green"])
    print()
    print(styled("=" * 72, color_code))
    print(styled(title, STYLE["bold"], color_code))
    print(styled("=" * 72, color_code))
    if items:
        summary_table(items)
    print()


def open_artifact(path: str | Path | None, *, label: str = "Artifact") -> bool:
    if path is None:
        return False
    target = Path(path).expanduser().resolve()
    if not target.exists():
        bullet(f"{label} not found, skip auto-open: {target}", kind="warn")
        return False
    if os.environ.get("FALL_DEMO_NO_OPEN", "").strip().lower() in {"1", "true", "yes"}:
        bullet(f"Auto-open disabled: {target}")
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:
        bullet(f"Could not auto-open {label}: {exc}", kind="warn")
        return False
    bullet(f"Opened {label}: {target}", kind="ok")
    return True


def run_with_guard(main_fn, *, script_name: str) -> int:
    enable_utf8_stdout()
    try:
        return int(main_fn())
    except KeyboardInterrupt:
        final_status(f"{script_name} interrupted by user", color="yellow")
        return 130
    except FileNotFoundError as exc:
        final_status(
            f"{script_name} failed",
            color="red",
            items=[("reason", "file_not_found"), ("path", str(exc))],
        )
        return 1
    except Exception as exc:
        final_status(
            f"{script_name} failed",
            color="red",
            items=[
                ("reason", type(exc).__name__),
                ("message", str(exc)),
                ("time", datetime.now().isoformat(timespec="seconds")),
            ],
        )
        print(styled("[TRACEBACK]", STYLE["bold"], STYLE["red"]))
        print(traceback.format_exc().rstrip())
        return 1
