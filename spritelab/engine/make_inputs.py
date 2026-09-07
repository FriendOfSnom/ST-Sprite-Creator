"""Build Gemini-ready inputs from real ST character art.

THE RULE (see memory: spritelab): never feed the in-game export. It is mirrored
AND upscaled ~1.12x from native, which costs you an extra resample before Gemini
even sees the art. Instead composite `outfit + face` at (0,0) - exactly what ST's
compose() does - straight from the stored PNGs at NATIVE resolution.

ST renders a pose mirrored whenever its `facing` is left, which is the DEFAULT
when character.yml has no `poses:` entry. So the "display" orientation (how the
character actually looks in game) is usually the horizontal flip of the stored
art. Orientation costs nothing in quality (a flip is lossless) and the aligner
auto-detects it, but display orientation is friendlier to prompt against.

Usage:  python spritelab/engine/make_inputs.py [character ...]
Writes: spritelab/inputs/<char>_<pose>_<outfit>_<W>x<H>_display.png
"""
import sys
import pathlib

import yaml
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHARS = ROOT / "normal_ST_Character_Folders"
OUT = ROOT / "spritelab" / "inputs"

# preferred base outfit, in order; falls back to the first available
PREFERRED = ["uniform", "casual", "casual_b", "sport", "athletic", "gym"]


def facing_is_left(char_dir: pathlib.Path, pose: str) -> bool:
    """ST defaults a pose to facing left (=mirrored on screen) unless the yml
    explicitly says otherwise."""
    yml = char_dir / "character.yml"
    if not yml.is_file():
        return True
    try:
        data = yaml.safe_load(yml.read_text()) or {}
    except Exception:
        return True
    facing = (data.get("poses", {}) or {}).get(pose, {}).get("facing", "left")
    return facing == "left"


def pick_outfit(outfits_dir: pathlib.Path):
    files = sorted(p for p in outfits_dir.iterdir()
                   if p.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"})
    if not files:
        return None
    by_stem = {p.stem.lower(): p for p in files}
    for want in PREFERRED:
        if want in by_stem:
            return by_stem[want]
    return files[0]


def neutral_face(faces_dir: pathlib.Path):
    """Face '0' is conventionally the neutral expression."""
    files = sorted(faces_dir.glob("*.*"))
    for f in files:
        if f.stem == "0":
            return f
    return files[0] if files else None


def build(char: str) -> int:
    char_dir = CHARS / char
    if not char_dir.is_dir():
        print(f"  [skip] no folder for {char}")
        return 0
    made = 0
    for pose_dir in sorted(p for p in char_dir.iterdir() if p.is_dir()):
        outfits, faces = pose_dir / "outfits", pose_dir / "faces" / "face"
        if not outfits.is_dir() or not faces.is_dir():
            continue
        o, f = pick_outfit(outfits), neutral_face(faces)
        if not o or not f:
            continue
        body = Image.open(o).convert("RGBA")
        comp = body.copy()
        comp.alpha_composite(Image.open(f).convert("RGBA"), (0, 0))  # ST: same origin
        if facing_is_left(char_dir, pose_dir.name):
            comp = comp.transpose(Image.FLIP_LEFT_RIGHT)
        white = Image.new("RGBA", comp.size, (255, 255, 255, 255))
        white.alpha_composite(comp)
        w, h = comp.size
        name = f"{char}_{pose_dir.name}_{o.stem}_{w}x{h}_display.png"
        white.convert("RGB").save(OUT / name)
        print(f"  {name}   (outfit {o.name} + face {f.name}, aspect {w/h:.5f})")
        made += 1
    return made


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    targets = sys.argv[1:] or ["zoey", "irene"]
    total = 0
    for c in targets:
        print(f"{c}:")
        total += build(c)
    print(f"\n{total} inputs written to {OUT}")
