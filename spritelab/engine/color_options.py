"""Build side-by-side comparison sheets for five colour-correction strategies.

One PNG per generation. Each ROW is a strategy, each COLUMN a representative
expression, 1:1 pixels, cropped to the head, in ST display orientation. The point
is to pick a strategy by eye, so nothing here is wired into align.py yet.

Strategies
ROUND 2. Round 1 verdict (user, by eye, confirmed by the held-out numbers):
  chest (the current default) was the WORST, below no correction at all - held-out
  9.84 vs 8.34 for none. ring and feather were the most consistent winners. clusters
  won clearly on sayaka, who has pink hair, because it is the only option that
  corrects HAIR. So round 2 drops none/chest and tries the synthesis: a ring or
  feather offset for SKIN, plus the paired hair offset on top.

  ring      sample the generated skin in a RING around the face layer - the seam the
            eye actually judges - target = the real face layer's skin mean
  feather   the ring offset, applied with a weight that is 1 at the face-layer
            boundary and decays with distance, so far-away regions are left alone
  clusters  PAIRED fit on the head band, where the reference and the generation show
            the SAME anatomy (same character, same pose, only the outfit differs), and
            SKIN and HAIR get their own offsets. Hair is otherwise never corrected -
            measured mean hair step 20.33 vs 7.59 for skin.

Usage:  python3 spritelab/engine/color_options.py [name_filter ...]
"""
import io
import sys
import csv
import pathlib

import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation, distance_transform_edt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align
from align import Reference, skin_mask

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHARS = ROOT / "normal_ST_Character_Folders"
ALIGNED = ROOT / "spritelab" / "aligned"
OUT = ROOT / "claude_io" / "out" / "colour_options"

OPTIONS = ["none", "feather", "feather+hair", "feather+haironly"]
N_COLS = 6                     # representative expressions per sheet
HAIR_TOL = 70.0                # colour ball around the fitted hair tone

# BACKGROUND REMOVAL RUNS FIRST, before any colour work, using THE APP'S OWN function
# and settings (isnet-anime, alpha_matting=True, fg=220, bg=55, erode=25,
# post_process=True, plus edge cleanup) - imported rather than reimplemented so this
# cannot drift from what the rest of ST Sprite Creator does.
#
# Why it has to come first: generations arrive opaque-on-white, and guessing the
# character from brightness fails on ST's pale palette - pure white is only 21.8 from
# pale skin (255,249,234), inside BODY_SKIN_TOL=45, so the background reads as skin.
sys.path.insert(0, str(ROOT / "src"))
from sprite_creator.api.gemini_client import strip_background_ai   # noqa: E402

_ALPHA_CACHE = {}


def character_alpha(png_path: pathlib.Path) -> np.ndarray:
    key = str(png_path)
    if key not in _ALPHA_CACHE:
        out = strip_background_ai(png_path.read_bytes())
        _ALPHA_CACHE[key] = np.asarray(
            Image.open(io.BytesIO(out)).convert("RGBA"))[:, :, 3]
    return _ALPHA_CACHE[key]


def facing_is_left(char_dir, pose):
    yml = char_dir / "character.yml"
    if not yml.is_file():
        return True
    try:
        data = yaml.safe_load(yml.read_text()) or {}
    except Exception:
        return True
    return (data.get("poses", {}) or {}).get(pose, {}).get("facing", "left") == "left"


def face_layer(pose_dir, size):
    """First expression, padded onto the full body canvas (ST composites at (0,0))."""
    fp = sorted((pose_dir / "faces" / "face").glob("*.*"), key=lambda p: (len(p.stem), p.stem))
    pad = Image.new("RGBA", size, (0, 0, 0, 0))
    pad.alpha_composite(Image.open(fp[0]).convert("RGBA"), (0, 0))
    return pad, fp


def corrections(raw: Image.Image, ref: Reference, pose_dir: pathlib.Path,
                alpha: np.ndarray):
    """Return {option: corrected RGBA image}."""
    G = align._rgb_on_white(raw)
    W, H = ref.size
    x0, y0, x1, y1 = ref.box
    sk, tone = skin_mask(ref.rgb[y0:y1, x0:x1], alpha=ref.alpha[y0:y1, x0:x1])
    out = {"none": raw}
    if tone is None or int(sk.sum()) < align.MIN_SKIN_PX:
        return {k: raw for k in OPTIONS}
    target = ref.rgb[y0:y1, x0:x1][sk].mean(0)

    pad, _ = face_layer(pose_dir, ref.size)
    covered = np.asarray(pad)[:, :, 3] > 200
    body = ref.alpha > 200
    # The generation is opaque-on-white, so the white BACKGROUND must be excluded or it
    # gets tinted. It also has to be excluded from `gen_skin`: pure white is only 21.8
    # away from pale ST skin (255,249,234), well inside BODY_SKIN_TOL=45, so a pale
    # character's background would otherwise be corrected as if it were her face.
    character = alpha > 200        # real BG removal, the app's own settings
    gen_skin = (np.linalg.norm(G - tone, axis=2) < align.BODY_SKIN_TOL) & character

    def apply(off, weight=None):
        w = character.astype(np.float32) if weight is None else weight * character
        arr = np.clip(G + off * w[..., None], 0, 255)
        return Image.fromarray(arr.astype(np.uint8)).convert("RGBA")

    # --- ring: generated skin hugging the face-layer boundary
    ring = binary_dilation(covered, np.ones((9, 9))) & ~covered & body
    rs = ring & gen_skin
    off_ring = target - G[rs].mean(0) if rs.sum() >= 300 else None
    out["ring"] = apply(off_ring) if off_ring is not None else raw

    # --- feather: same offset, weight decays away from the face layer
    if off_ring is not None:
        dist = distance_transform_edt(~covered)
        tau = max(8.0, (y1 - y0) * 0.9)
        out["feather"] = apply(off_ring, np.exp(-dist / tau).astype(np.float32))
    else:
        out["feather"] = raw

    # --- clusters: PAIRED fit on the head band, skin and hair separately.
    # The head is the same anatomy in both images (only the outfit differs), so the
    # reference and the generation can be compared pixel to pixel there. Clothing is
    # excluded by staying above the shoulders.
    fh = y1 - y0
    band = np.zeros((H, W), bool)
    band[max(0, int(y0 - fh * 1.4)):min(H, int(y1 + fh * 0.35)), :] = True
    usable = band & body & ~covered
    ref_skin = np.linalg.norm(ref.rgb - tone, axis=2) < align.BODY_SKIN_TOL
    ms = usable & ref_skin
    mh = usable & ~ref_skin
    arr = G.copy()
    gen_other = character & ~gen_skin            # hair/clothing, never the background
    off_hair = None
    if ms.sum() >= 300:
        arr[gen_skin] = np.clip(arr[gen_skin] + (ref.rgb[ms] - G[ms]).mean(0), 0, 255)
    if mh.sum() >= 300:
        oh = (ref.rgb[mh] - G[mh]).mean(0)
        if np.linalg.norm(oh) <= align.MAX_SANE_OFFSET:
            off_hair = oh
            arr[gen_other] = np.clip(arr[gen_other] + oh, 0, 255)
    out["clusters"] = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")

    # --- the synthesis: feather offset on SKIN, paired hair offset on HAIR.
    # Held-out means over 14 generations (lower better):
    #            none   chest    ring  feather  clusters
    #   skin     8.32    7.43    5.98     5.88      7.53
    #   hair     9.48   19.04   14.44    12.51      4.89
    # ring/feather do NOT leave hair alone - they apply globally, so a skin-fitted
    # offset gets smeared over the hair and makes it WORSE than no correction.
    # feather smears less than ring, which is the only real difference between them.
    # clusters is the only option that improves hair, but has the worst skin tail
    # (28.92) and forces two offsets to meet at a hard threshold.
    def combined(weight=None):
        a = G.copy()
        w = np.ones((H, W), np.float32) if weight is None else weight
        w = w * character
        if off_ring is not None:
            a += off_ring * (w * gen_skin)[..., None]
        if off_hair is not None:
            a += off_hair * (w * gen_other)[..., None]
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")

    fw = np.exp(-distance_transform_edt(~covered) / max(8.0, (y1 - y0) * 0.9)).astype(np.float32)
    out["feather+hair"] = combined(fw)

    # --- feather+hairONLY: the same, but the hair offset touches ONLY HAIR.
    # Measured: 66-86% of the pixels `gen_other` covers are CLOTHING, not hair. The
    # offset is fitted on hair and was recolouring the entire outfit Gemini invented -
    # content we have no reference for and no business shifting. That is very likely
    # why feather+hair looked worse than plain feather on everyone except sayaka,
    # whose crop is mostly hair and whose sport outfit is tiny.
    # Hair is selected BY COLOUR, not by a y cut-off: a horizontal band boundary would
    # draw a visible line across long hair (sayaka's falls well below the head).
    if off_hair is not None and mh.sum() >= 300:
        hair_tone = np.median(G[gen_other & band], axis=0)
        hair_only = (np.linalg.norm(G - hair_tone, axis=2) < HAIR_TOL) & gen_other
        a = G.copy()
        if off_ring is not None:
            a += off_ring * (fw * character * gen_skin)[..., None]
        a += off_hair * (fw * character * hair_only)[..., None]
        out["feather+haironly"] = Image.fromarray(
            np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
    else:
        out["feather+haironly"] = out["feather"]
    return out


def build(gen_name, char, pose, outfit):
    pose_dir = CHARS / char / pose
    ref = Reference.from_pose(str(pose_dir), outfit=outfit)
    raw_path = ALIGNED / f"{pathlib.Path(gen_name).stem}__aligned.png"
    raw = Image.open(raw_path).convert("RGBA")
    variants = corrections(raw, ref, pose_dir, character_alpha(raw_path))

    pad, faces = face_layer(pose_dir, ref.size)
    idx = np.linspace(0, len(faces) - 1, min(N_COLS, len(faces))).round().astype(int)
    picks = [faces[i] for i in dict.fromkeys(idx)]
    flip = facing_is_left(CHARS / char, pose)

    x0, y0, x1, y1 = ref.box
    px_, pt_, pb_ = int((x1 - x0) * 0.5), int((y1 - y0) * 0.8), int((y1 - y0) * 0.6)
    cx0, cy0 = max(0, x0 - px_), max(0, y0 - pt_)
    cx1, cy1 = min(ref.size[0], x1 + px_), min(ref.size[1], y1 + pb_)

    grid = []
    for opt in OPTIONS:
        row = []
        for f in picks:
            comp = variants[opt].copy()
            comp.alpha_composite(Image.open(f).convert("RGBA"), (0, 0))
            bg = Image.new("RGBA", comp.size, (255, 255, 255, 255))
            bg.alpha_composite(comp)
            c = bg.convert("RGB").crop((cx0, cy0, cx1, cy1))
            if flip:
                c = c.transpose(Image.FLIP_LEFT_RIGHT)
            row.append(c)
        grid.append((opt, row))

    tw, th = grid[0][1][0].size
    LBLW, PAD, TOP = 96, 6, 26
    sheet = Image.new("RGB", (LBLW + len(picks) * (tw + PAD) + PAD,
                              TOP + len(OPTIONS) * (th + PAD) + PAD), (245, 245, 248))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 8), f"{pathlib.Path(gen_name).stem}   colour-correction options"
                     f"   (rows, top to bottom: {', '.join(OPTIONS)})", fill=(15, 15, 20))
    for r, (opt, row) in enumerate(grid):
        py = TOP + PAD + r * (th + PAD)
        d.text((PAD, py + th // 2 - 5), opt, fill=(20, 20, 28))
        for c, im in enumerate(row):
            sheet.paste(im, (LBLW + c * (tw + PAD), py))
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT / f"{pathlib.Path(gen_name).stem}__options.png")
    return sheet.size


def main():
    rows = [r for r in csv.DictReader(open(ROOT / "spritelab/results/batch.csv"))
            if r.get("char") and r["verdict"] == "PASS" and "full_body" not in r["variant"]]
    if len(sys.argv) > 1:
        rows = [r for r in rows if any(a in r["gen"] for a in sys.argv[1:])]
    for i, r in enumerate(rows, 1):
        size = build(r["gen"], r["char"], r["pose"], r["outfit"])
        print(f"[{i}/{len(rows)}] {r['gen']}  -> {size}", flush=True)
    print(f"\n{len(rows)} sheets in {OUT}")


if __name__ == "__main__":
    main()
