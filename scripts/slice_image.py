"""
Stage 5: Smart-crop raw images to target aspect ratio.

Usage:
    python scripts/slice_image.py
    python scripts/slice_image.py --shot 5
    python scripts/slice_image.py --project <dir>
"""
import os, sys, json, shutil
from pathlib import Path

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT = _resolve_project()
SCRIPT  = PROJECT / "script.json"
IMAGES  = PROJECT / "images"
SLICES  = PROJECT / "slices"


def target_size(aspect_ratio):
    return {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1":  (1080, 1080),
    }.get(aspect_ratio, (1920, 1080))


def smart_crop(img_path, out_path, tw, th):
    if not PIL_OK:
        shutil.copy(img_path, out_path)
        print(f"  (PIL missing, copied as-is) {out_path.name}")
        return
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    new_w, new_h = int(iw * scale), int(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - tw) // 2
    top  = (new_h - th) // 2
    img  = img.crop((left, top, left + tw, top + th))
    img.save(out_path, "PNG", optimize=True)
    print(f"  OK {out_path.name}  ({tw}x{th})")


def main():
    SLICES.mkdir(exist_ok=True)
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    ar = script.get("aspect_ratio", "16:9")
    tw, th = target_size(ar)

    force_shot = None
    if "--shot" in sys.argv:
        idx = sys.argv.index("--shot")
        force_shot = int(sys.argv[idx + 1])

    shots = script["shots"]
    if force_shot is not None:
        shots = [s for s in shots if s["id"] == force_shot]

    print(f"[slice] Slicing {len(shots)} image(s) to {tw}x{th} ({ar})")
    ok = 0
    for shot in shots:
        img_path = IMAGES / f"shot_{shot['id']:03d}.png"
        out_path = SLICES / f"shot_{shot['id']:03d}_{ar.replace(':','x')}.png"
        if not img_path.exists():
            print(f"  - shot_{shot['id']:03d}.png missing")
            continue
        smart_crop(img_path, out_path, tw, th)
        ok += 1

    print(f"[slice] Done {ok}/{len(shots)}")


if __name__ == "__main__":
    main()
