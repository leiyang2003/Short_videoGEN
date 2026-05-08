#!/usr/bin/env python3
"""Replace character portrait backgrounds with a flat light gray-white color."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_COLOR = (243, 243, 241)


def parse_color(value: str) -> tuple[int, int, int]:
    raw = str(value or "").strip()
    if raw.startswith("#") and len(raw) == 7:
        return tuple(int(raw[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) == 3:
        rgb = tuple(max(0, min(255, int(part))) for part in parts)
        return rgb  # type: ignore[return-value]
    raise ValueError("color must be #RRGGBB or R,G,B")


def flatten_image(path: Path, *, color: tuple[int, int, int], model: str) -> None:
    try:
        from PIL import Image
        from rembg import new_session, remove
    except Exception as exc:
        raise RuntimeError(
            "flatten background requires optional dependencies: pip install rembg onnxruntime"
        ) from exc

    source = Image.open(path).convert("RGB")
    session = new_session(model)
    cutout = remove(source, session=session).convert("RGBA")
    background = Image.new("RGBA", source.size, (*color, 255))
    background.alpha_composite(cutout)
    background.convert("RGB").save(path, quality=95)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, nargs="+", help="Character portrait images to update in place.")
    parser.add_argument("--color", default="#f3f3f1", help="Flat background color, default #f3f3f1.")
    parser.add_argument("--model", default="u2net_human_seg", help="rembg model name, default u2net_human_seg.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    color = parse_color(args.color)
    for item in args.images:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        flatten_image(path, color=color, model=str(args.model or "u2net_human_seg"))
        print(f"[OK] flattened background: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
