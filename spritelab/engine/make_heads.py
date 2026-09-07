"""Build a WHOLE-HEAD expression layer: take the head off the generation, put it on
the real body.

Supersedes the crop-to-existing-alpha approach, which was WRONG: a shipped face layer's
alpha covers only the DRAWN FEATURES (eyes, brows, mouth) as disconnected blobs, not the
head. Cutting a new generation with it pastes new eye/mouth fragments over the ORIGINAL
face and yields a chimera of two drawings.

Neck line is found from the silhouette: below the chin, the narrowest row is the neck.
Cutting there hides the seam where the head meets the collar.
"""
import io, sys, csv, pathlib
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from align import Reference
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from sprite_creator.api.gemini_client import strip_background_ai

ALIGNED = ROOT/"spritelab"/"aligned_expr"
HEADS   = ROOT/"spritelab"/"heads_out"
SHEETS  = ROOT/"spritelab"/"sheets"
CHARS   = ROOT/"normal_ST_Character_Folders"
FEATHER = 3          # px of soft edge at the neck cut


def neck_row(alpha, chin_y, face_h, H):
    """Narrowest silhouette row in the band just below the chin."""
    lo, hi = min(H-2, chin_y), min(H, chin_y + int(face_h * 1.1))
    if hi - lo < 4:
        return min(H-1, chin_y + max(2, face_h // 6))
    widths = (alpha[lo:hi] > 128).sum(1).astype(float)
    widths[widths == 0] = 1e9
    return lo + int(np.argmin(widths))


def build(key, char, pose, outfit):
    ref = Reference.from_pose(str(CHARS/char/pose), outfit=outfit, anchor="body")
    al = Image.open(ALIGNED/f"{key}__aligned.png").convert("RGBA")
    buf = io.BytesIO(); al.save(buf, format="PNG")
    ca = np.asarray(Image.open(io.BytesIO(strip_background_ai(buf.getvalue()))).convert("RGBA"))[:, :, 3]

    W, H = ref.size
    x0, y0, x1, y1 = ref.box
    ny = neck_row(ca, y1, y1 - y0, H)
    keep = np.zeros((H, W), np.float32)
    keep[:ny] = 1.0
    for i in range(FEATHER):                       # soften the cut so it does not read as a line
        r = ny + i
        if r < H:
            keep[r] = 1.0 - (i + 1) / (FEATHER + 1)
    a = (ca.astype(np.float32) * keep).clip(0, 255).astype(np.uint8)
    layer = Image.fromarray(np.dstack([np.asarray(al.convert("RGB")), a]).astype(np.uint8), "RGBA")
    HEADS.mkdir(parents=True, exist_ok=True)
    layer.save(HEADS/f"{key}__head.png")

    outf = sorted((CHARS/char/pose/"outfits").glob("*.*"))
    body = Image.open(next((p for p in outf if p.stem == outfit), outf[0])).convert("RGBA")
    # coverage check: original head pixels the new head fails to cover
    orig_head = (np.asarray(body)[:, :, 3] > 16) & (keep > 0.5)
    uncovered = orig_head & (a < 128)
    cov = 100.0 * uncovered.sum() / max(1, orig_head.sum())

    def onw(im):
        b = Image.new("RGBA", im.size, (255,255,255,255)); b.alpha_composite(im); return b.convert("RGB")
    fp = sorted((CHARS/char/pose/"faces"/"face").glob("*.*"), key=lambda p:(len(p.stem),p.stem))[0]
    o = body.copy(); o.alpha_composite(Image.open(fp).convert("RGBA"), (0,0))
    n = body.copy(); n.alpha_composite(layer, (0,0))
    px,pt,pb = int((x1-x0)*0.7), int((y1-y0)*1.3), int((y1-y0)*1.3)
    C = (max(0,x0-px), max(0,y0-pt), min(W,x1+px), min(H,y1+pb))
    return [onw(o).crop(C), onw(n).crop(C)], ny, cov


def main():
    rows = [r for r in csv.DictReader(open(ROOT/"spritelab/results/expr.csv")) if r.get("char")]
    if len(sys.argv) > 1:
        rows = [r for r in rows if any(a in r["gen"] for a in sys.argv[1:])]
    cells = []
    for r in rows:
        key = pathlib.Path(r["gen"]).stem[:-len("_face")]
        try:
            ps, ny, cov = build(key, r["char"], r["pose"], r["outfit"])
            cells.append((key, ps, cov)); print(f"  {key:26} neck y={ny:4d}  uncovered {cov:5.2f}%", flush=True)
        except Exception as e:
            print(f"  {key} FAILED {e}", flush=True)
    if not cells: return
    H = max(p.height for _,ps,_ in cells for p in ps); W = max(p.width for _,ps,_ in cells for p in ps)
    PAD, LBL, TOP, cols = 8, 15, 22, 4
    cw = 2*W+6; rn = (len(cells)+cols-1)//cols
    sheet = Image.new("RGB", (cols*(cw+PAD)+PAD, rn*(H+LBL+PAD)+PAD+TOP), (244,244,248))
    d = ImageDraw.Draw(sheet)
    d.text((PAD,6), "WHOLE HEAD taken from the generation and placed on the REAL body.  "
                    "Left = original, right = new.", fill=(15,15,20))
    for i,(k,ps,cov) in enumerate(cells):
        px = PAD+(i%cols)*(cw+PAD); py = TOP+PAD+(i//cols)*(H+LBL+PAD)
        d.text((px,py+2), f"{k}   uncovered {cov:.2f}%", fill=(30,30,38))
        for j,im in enumerate(ps): sheet.paste(im, (px+j*(W+6), py+LBL))
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEETS/"EXPR_whole_head_on_real_body.png")
    print(f"\n-> {SHEETS/'EXPR_whole_head_on_real_body.png'} {sheet.size}")

if __name__ == "__main__":
    main()
