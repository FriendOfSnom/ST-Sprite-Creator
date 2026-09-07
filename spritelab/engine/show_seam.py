"""Show EXACTLY which pixels came from the new generated head and which are original.

Panel 1: the composite as it would ship.
Panel 2: same, with everything taken from the NEW head tinted, and the layer's alpha
         boundary traced. Anything untinted is the ORIGINAL character, untouched.
"""
import sys, csv, pathlib
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from align import Reference
ROOT = pathlib.Path(__file__).resolve().parents[2]
HEADS, SHEETS, CHARS = ROOT/"spritelab"/"heads_out", ROOT/"spritelab"/"sheets", ROOT/"normal_ST_Character_Folders"
Z = 2

def build(key, char, pose, outfit):
    ref = Reference.from_pose(str(CHARS/char/pose), outfit=outfit, anchor="body")
    layer = Image.open(HEADS/f"{key}__head.png").convert("RGBA")
    outf = sorted((CHARS/char/pose/"outfits").glob("*.*"))
    body = Image.open(next((p for p in outf if p.stem == outfit), outf[0])).convert("RGBA")
    c = body.copy(); c.alpha_composite(layer, (0, 0))
    bg = Image.new("RGBA", c.size, (255,255,255,255)); bg.alpha_composite(c)
    comp = np.asarray(bg.convert("RGB")).astype(np.float32)

    a = np.asarray(layer)[:, :, 3]
    new = a > 128
    edge = new & ~binary_erosion(new, np.ones((3, 3)))
    marked = comp.copy()
    marked[new] = marked[new] * 0.62 + np.array([0., 210., 120.]) * 0.38   # tint what is NEW
    marked[edge] = [255, 0, 220]                                          # trace the boundary
    x0, y0, x1, y1 = ref.box
    ny = int(np.nonzero((a > 0).any(1))[0].max()) + 1
    C = (max(0, x0-int((x1-x0)*0.75)), max(0, y0-int((y1-y0)*1.35)),
         min(ref.size[0], x1+int((x1-x0)*0.75)), min(ref.size[1], ny+int((y1-y0)*0.55)))
    out = []
    for arr in (comp, marked):
        im = Image.fromarray(arr.clip(0,255).astype(np.uint8)).crop(C)
        out.append(im.resize((im.width*Z, im.height*Z), Image.NEAREST))
    return out

def main():
    rows = [r for r in csv.DictReader(open(ROOT/"spritelab/results/expr.csv")) if r.get("char")]
    if len(sys.argv) > 1:
        rows = [r for r in rows if any(a in r["gen"] for a in sys.argv[1:])]
    # WORST FIT FIRST, best last, by body-band agreement. Reading order then matches
    # confidence order, and it shows whether the number predicts what the eye sees.
    rows.sort(key=lambda r: -float(r["body_pct"]))
    cells = []
    for r in rows:
        key = pathlib.Path(r["gen"]).stem[:-len("_face")]
        try: cells.append((f"{key}   body {float(r['body_pct']):.2f}%",
                           build(key, r["char"], r["pose"], r["outfit"])))
        except Exception as e: print(f"  {key} FAILED {e}")
    H = max(p.height for _,ps in cells for p in ps); W = max(p.width for _,ps in cells for p in ps)
    PAD, LBL, TOP, cols = 8, 15, 26, 3
    cw = 2*W+6; rn = (len(cells)+cols-1)//cols
    sheet = Image.new("RGB", (cols*(cw+PAD)+PAD, rn*(H+LBL+PAD)+PAD+TOP), (244,244,248))
    d = ImageDraw.Draw(sheet)
    d.text((PAD,6), "ORDERED WORST FIT FIRST (top-left) TO BEST (bottom-right), by body-band agreement.   "
                    "GREEN TINT = pixels from the new generated head.  MAGENTA = the layer boundary.  "
                    "Untinted = ORIGINAL, untouched.", fill=(15,15,20))
    for i,(k,ps) in enumerate(cells):
        px = PAD+(i%cols)*(cw+PAD); py = TOP+PAD+(i//cols)*(H+LBL+PAD)
        d.text((px,py+2), k, fill=(30,30,38))
        for j,im in enumerate(ps): sheet.paste(im, (px+j*(W+6), py+LBL))
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEETS/"EXPR_seam_visible.png")
    print(f"-> {SHEETS/'EXPR_seam_visible.png'} {sheet.size}  ({len(cells)} characters)")

if __name__ == "__main__":
    main()
