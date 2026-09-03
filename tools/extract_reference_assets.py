"""Extract the exact Orb and startup mark from the supplied reference image."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


FRAME_COUNT = 24
FRAME_SIZE = 768
HOME_PANEL_BOX = (40, 45, 891, 881)
STARTUP_PANEL_BOX = (918, 45, 1631, 881)
ORB_CROP_BOX = (245, 220, 710, 685)
STARTUP_MARK_BOX = (1228, 310, 1308, 390)


def _reference_alpha(crop: Image.Image, center: tuple[float, float], core_radius: float, halo_radius: float) -> Image.Image:
    """Keep the dark glass body and only bright reference pixels outside it."""

    rgb = crop.convert("RGB")
    luminance = ImageOps.grayscale(rgb)
    width, height = crop.size
    pixels = luminance.load()
    alpha = Image.new("L", crop.size, 0)
    output = alpha.load()
    cx, cy = center
    for y in range(height):
        for x in range(width):
            distance = math.hypot(x - cx, y - cy)
            light = pixels[x, y]
            if distance <= core_radius:
                value = 255
            elif distance <= halo_radius:
                # Preserve bright source pixels at full opacity.  This keeps
                # the extracted highlight identical after compositing while
                # still fading the low-luminance panel texture.
                value = max(0, min(255, (light - 15) * 6))
            else:
                value = 0
            if y > cy + core_radius * 0.70:
                value = max(value, max(0, min(220, (light - 11) * 5)))
            output[x, y] = value
    # The reference already contains its own antialiasing.  Do not blur the
    # mask: filtering alpha would premultiply the top highlight and shift its
    # visible boundary by several pixels in the runtime widget.
    return alpha


def _extract_orb(reference: Image.Image, destination: Path) -> Image.Image:
    crop = reference.crop(ORB_CROP_BOX)
    center = (crop.width / 2.0, crop.height / 2.0)
    alpha = _reference_alpha(crop, center, core_radius=191.0, halo_radius=222.0)
    crop.putalpha(alpha)
    # Keep the source crop at its native 465px resolution.  Upscaling the
    # RGBA image before runtime downsampling would premultiply the transparent
    # halo and visibly darken the bright top highlight.
    master = crop
    destination.parent.mkdir(parents=True, exist_ok=True)
    master.save(destination, "PNG", optimize=True)
    return master


def _extract_startup_mark(reference: Image.Image, destination: Path) -> None:
    crop = reference.crop(STARTUP_MARK_BOX).convert("RGB")
    luminance = ImageOps.grayscale(crop)
    alpha = luminance.point(lambda value: max(0, min(255, (value - 14) * 5)))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.35))
    crop.putalpha(alpha)
    mark = crop.resize((256, 256), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mark.save(destination, "PNG", optimize=True)


def _state_frame(master: Image.Image, state: str, index: int) -> Image.Image:
    # Every state is a strict derivative of the extracted reference Orb.  Only
    # very small luminance variations are allowed; the silhouette and text stay
    # pixel-identical across the sequence.
    phase = index / FRAME_COUNT * math.tau
    amount = {
        "listening": 1.0 + 0.025 * (0.5 + 0.5 * math.sin(phase)),
        "thinking": 1.0 + 0.018 * (0.5 + 0.5 * math.sin(phase * 1.4)),
        "speaking": 1.0 + 0.032 * (0.5 + 0.5 * math.sin(phase)),
    }[state]
    return ImageEnhance.Brightness(master).enhance(amount)


def _save_state_frames(master: Image.Image, root: Path) -> None:
    for state in ("listening", "thinking", "speaking"):
        target = root / state
        target.mkdir(parents=True, exist_ok=True)
        for index in range(FRAME_COUNT):
            frame = _state_frame(master, state, index).resize((FRAME_SIZE, FRAME_SIZE), Image.Resampling.LANCZOS)
            frame.save(target / f"frame_{index:03d}.png", "PNG", optimize=True)


def _save_asset_preview(image: Image.Image, destination: Path) -> None:
    background = Image.new("RGBA", image.size, (7, 7, 9, 255))
    Image.alpha_composite(background, image).save(destination, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    reference = Image.open(args.reference).convert("RGB")
    if reference.size != (1672, 941):
        raise ValueError(f"Unexpected reference size: {reference.size}")

    root = args.root.resolve()
    orb_root = root / "assets" / "orb"
    master_path = orb_root / "master" / "orb_reference_master.png"
    master = _extract_orb(reference, master_path)
    master.save(orb_root / "orb_idle.png", "PNG", optimize=True)
    _save_state_frames(master, orb_root)
    _extract_startup_mark(reference, root / "assets" / "startup" / "startup_orb.png")

    preview_root = root / "assets" / "preview"
    preview_root.mkdir(parents=True, exist_ok=True)
    for filename, image in {
        "orb_idle_reference_match.png": master,
        "orb_listening_reference_match.png": _state_frame(master, "listening", 8),
        "orb_thinking_reference_match.png": _state_frame(master, "thinking", 11),
        "orb_speaking_reference_match.png": _state_frame(master, "speaking", 14),
    }.items():
        _save_asset_preview(image, preview_root / filename)

    (root / "diagnostics").mkdir(parents=True, exist_ok=True)
    reference.crop(HOME_PANEL_BOX).save(root / "diagnostics" / "reference_target_home.png", "PNG")
    reference.crop(STARTUP_PANEL_BOX).save(root / "diagnostics" / "reference_target_startup.png", "PNG")


if __name__ == "__main__":
    main()
