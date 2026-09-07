"""Register every generation in spritelab/generated/ against its reference pose.

Pairs a generation to a reference by longest matching `<char>_<pose>_<outfit>` prefix.
Writes one CSV row per pair AS IT COMPLETES so the run can be watched and survives
being interrupted.

For every generation that PASSES verification it also writes a faces contact sheet:
every expression in that pose composited onto the new outfit exactly the way ST does
it (same origin, face over outfit, mirrored if the pose faces left), cropped to the
head at 1:1 so alignment and colour can be judged by eye.

Usage:  python3 spritelab/engine/run_batch.py [name_filter ...]
"""
import io
import sys
import csv
import time
import pathlib
import traceback

import numpy as np
import yaml
from scipy.ndimage import binary_dilation
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align
from align import (Reference, find_transform, apply_transform, color_match,
                   residual, edge_energy, on_white_gray, skin_mask, color_gate,
                   verify)

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Background removal runs BEFORE colour work, using the app's own function and settings
# so this cannot drift from the rest of ST Sprite Creator.
sys.path.insert(0, str(ROOT / "src"))
from sprite_creator.api.gemini_client import strip_background_ai   # noqa: E402
INPUTS = ROOT / "spritelab" / "inputs"
GEN = ROOT / "spritelab" / "generated"
ALIGNED = ROOT / "spritelab" / "aligned"
RESULTS = ROOT / "spritelab" / "results"
SHEETS = ROOT / "claude_io" / "out" / "faces"
CHARS = ROOT / "normal_ST_Character_Folders"

FIELDS = ["gen", "char", "pose", "outfit", "variant", "ref_w", "ref_h", "gen_w", "gen_h",
          "ref_ar", "gen_ar", "ar_drift", "analytic", "mirrored", "hit_rail",
          "sx", "sy", "dx", "dy", "score",
          "face_pct", "face_mean", "frame_pct", "frame_mean", "crisp_pct",
          "off_r", "off_g", "off_b", "off_mag", "colour_applied",
          "seam_before", "seam_after", "skin_px", "gate", "verdict", "why",
          "secs", "note"]


def references():
    out = {}
    for p in sorted(INPUTS.glob("*_display.png")):
        parts = p.stem.split("_")
        char, pose, outfit = parts[0], parts[1], "_".join(parts[2:-2])
        out[f"{char}_{pose}_{outfit}"] = (p, char, pose, outfit)
    return out


def pair(gen_stem, refs):
    best = None
    for k in refs:
        if gen_stem == k or gen_stem.startswith(k + "_"):
            if best is None or len(k) > len(best):
                best = k
    return best


def facing_is_left(char_dir: pathlib.Path, pose: str) -> bool:
    """ST defaults a pose to facing left (mirrored on screen). See character.py
    create_pose(): facingString = "left" before the poses_data lookup."""
    yml = char_dir / "character.yml"
    if not yml.is_file():
        return True
    try:
        data = yaml.safe_load(yml.read_text()) or {}
    except Exception:
        return True
    return (data.get("poses", {}) or {}).get(pose, {}).get("facing", "left") == "left"


def seam_step(arr, mask, face_skin):
    """Colour distance between the real face-layer skin and the generated skin in a
    RING hugging the face-layer boundary - the seam the eye actually judges, and the
    one `color_match(mode="feather")` targets.

    It used to measure the CHEST instead, which made feather look useless (12.58 ->
    12.10) because feather deliberately decays away from the face and leaves the chest
    alone. Measured at the boundary the same run is 7.45 -> 1.20.

    The mask is FIXED (taken from the uncorrected image) so both cases score the same
    pixels - scoring different pixel sets once made a correction look like it hurt.""" 
    if mask is None or int(mask.sum()) < 300:
        return None
    return float(np.linalg.norm(face_skin - arr[mask].mean(0)))


def faces_sheet(body: Image.Image, pose_dir: pathlib.Path, char_dir: pathlib.Path,
                pose_name: str, ref: Reference, out_path: pathlib.Path, title: str):
    """Every expression composited onto the new outfit, ST-style, head-cropped 1:1."""
    faces = sorted((pose_dir / "faces" / "face").glob("*.*"),
                   key=lambda p: (len(p.stem), p.stem))
    if not faces:
        return None
    flip = facing_is_left(char_dir, pose_name)
    x0, y0, x1, y1 = ref.box
    pad_x, pad_top, pad_bot = int((x1 - x0) * 0.55), int((y1 - y0) * 0.85), int((y1 - y0) * 0.75)
    cx0, cy0 = max(0, x0 - pad_x), max(0, y0 - pad_top)
    cx1, cy1 = min(body.width, x1 + pad_x), min(body.height, y1 + pad_bot)

    tiles = []
    for f in faces:
        comp = body.copy()
        comp.alpha_composite(Image.open(f).convert("RGBA"), (0, 0))   # ST: same origin
        bg = Image.new("RGBA", comp.size, (255, 255, 255, 255))
        bg.alpha_composite(comp)
        crop = bg.convert("RGB").crop((cx0, cy0, cx1, cy1))
        if flip:                                    # ST flips the WHOLE composite
            crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
        tiles.append((f.stem, crop))

    tw, th = tiles[0][1].size
    cols = min(6, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    LBL, PAD = 16, 8
    sheet = Image.new("RGB", (cols * (tw + PAD) + PAD, rows * (th + LBL + PAD) + PAD + 22),
                      (245, 245, 248))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 6), title, fill=(15, 15, 20))
    for i, (name, im) in enumerate(tiles):
        px = PAD + (i % cols) * (tw + PAD)
        py = 22 + PAD + (i // cols) * (th + LBL + PAD)
        sheet.paste(im, (px, py + LBL))
        d.text((px, py + 2), f"face {name}", fill=(40, 40, 48))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return len(tiles)


def run_one(gen_path, key, refs):
    ref_path, char, pose, outfit = refs[key]
    variant = gen_path.stem[len(key):].lstrip("_") or "base"
    pose_dir = CHARS / char / pose
    ref = Reference.from_pose(str(pose_dir), outfit=outfit)
    cand = Image.open(gen_path).convert("RGBA")

    t0 = time.time()
    t = find_transform(cand, ref)
    raw = apply_transform(cand, t, ref)
    buf = io.BytesIO()
    raw.save(buf, format="PNG")
    char_alpha = np.asarray(Image.open(
        io.BytesIO(strip_background_ai(buf.getvalue()))).convert("RGBA"))[:, :, 3]
    fixed, coef = color_match(raw, ref, alpha=char_alpha)     # mode="feather" default
    secs = time.time() - t0

    ALIGNED.mkdir(parents=True, exist_ok=True)
    raw.save(ALIGNED / f"{gen_path.stem}__aligned.png")
    fixed.save(ALIGNED / f"{gen_path.stem}__aligned_fixed.png")

    face_abs, face_pct = residual(fixed, ref, shrink=0.30)
    frame_abs, frame_pct = residual(fixed, ref, shrink=1.0)
    crisp = 100 * edge_energy(on_white_gray(fixed)) / edge_energy(ref.gray)
    ok, why = verify(fixed, ref, t)

    x0, y0, x1, y1 = ref.box
    sk, tone = skin_mask(ref.rgb[y0:y1, x0:x1], alpha=ref.alpha[y0:y1, x0:x1])
    face_skin = ref.rgb[y0:y1, x0:x1][sk].mean(0) if int(sk.sum()) >= 200 else None

    RAW = align._rgb_on_white(raw)
    FIX = align._rgb_on_white(fixed)
    mask = None
    if face_skin is not None and tone is not None:
        covered = ref.face_alpha > 200
        ring = (binary_dilation(covered, np.ones((9, 9))) & ~covered
                & (ref.alpha > 200) & (char_alpha > 200))
        mask = ring & (np.linalg.norm(RAW - tone, axis=2) < align.BODY_SKIN_TOL)
    sb = seam_step(RAW, mask, face_skin) if face_skin is not None else None
    sa = seam_step(FIX, mask, face_skin) if face_skin is not None else None

    off = [c[1] for c in coef] if coef else [float("nan")] * 3
    status, _ = color_gate(fixed, ref, coef)

    n_faces = None
    if ok:
        n_faces = faces_sheet(fixed, pose_dir, CHARS / char, pose, ref,
                              SHEETS / f"{gen_path.stem}__faces.png",
                              f"{gen_path.stem}   all expressions on the new outfit"
                              f"   (face {face_pct:.2f}%, seam {sa:.2f})" if sa is not None else f"   (face {face_pct:.2f}%, seam n/a)")

    rw, rh = ref.size
    gw, gh = cand.size
    return {
        "gen": gen_path.name, "char": char, "pose": pose, "outfit": outfit,
        "variant": variant, "ref_w": rw, "ref_h": rh, "gen_w": gw, "gen_h": gh,
        "ref_ar": round(rw / rh, 5), "gen_ar": round(gw / gh, 5),
        "ar_drift": round(abs(gw / gh - rw / rh), 5),
        "analytic": t.analytic, "mirrored": t.mirrored, "hit_rail": t.hit_rail,
        "sx": round(t.sx, 5), "sy": round(t.sy, 5), "dx": t.dx, "dy": t.dy,
        "score": round(t.score, 1),
        "face_pct": round(face_pct, 2), "face_mean": round(face_abs, 2),
        "frame_pct": round(frame_pct, 2), "frame_mean": round(frame_abs, 2),
        "crisp_pct": round(crisp, 1),
        "off_r": round(off[0], 2), "off_g": round(off[1], 2), "off_b": round(off[2], 2),
        "off_mag": round(float(np.linalg.norm(off)), 2),
        "colour_applied": coef is not None,
        "seam_before": None if sb is None else round(sb, 2),
        "seam_after": None if sa is None else round(sa, 2),
        "skin_px": int(sk.sum()), "gate": status,
        "verdict": "PASS" if ok else "REJECT", "why": "; ".join(why),
        "secs": round(secs, 1), "note": "" if n_faces is None else f"{n_faces} faces",
    }


def main():
    refs = references()
    gens = sorted(GEN.glob("*.png"))
    if len(sys.argv) > 1:
        gens = [g for g in gens if any(a in g.name for a in sys.argv[1:])]
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "batch.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        fh.flush()
        for i, g in enumerate(gens, 1):
            key = pair(g.stem, refs)
            print(f"[{i}/{len(gens)}] {g.name}", flush=True)
            if key is None:
                w.writerow({"gen": g.name, "note": "no reference match"})
                fh.flush()
                continue
            try:
                row = run_one(g, key, refs)
            except Exception as e:
                traceback.print_exc()
                w.writerow({"gen": g.name, "note": f"ERROR {e}"})
                fh.flush()
                continue
            w.writerow(row)
            fh.flush()
            print(f"        {row['secs']:5.1f}s  {row['verdict']:6}  "
                  f"face {row['face_pct']:5.2f}%  frame {row['frame_pct']:5.2f}%  "
                  f"crisp {row['crisp_pct']:5.1f}%  seam {row['seam_before']} -> {row['seam_after']}"
                  f"{'  ' + row['why'] if row['why'] else ''}", flush=True)
    print(f"\nwrote {out}", flush=True)


if __name__ == "__main__":
    main()
