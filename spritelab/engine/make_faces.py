"""Harvest a new FACE LAYER from a registered expression generation.

The generated BODY is discarded entirely - we only take the head. The new face layer
is cut with the EXISTING face layer's own alpha, so coverage is identical to what the
character already ships with and it cannot fail to cover the head underneath. That is
the safe option for existing characters (see big-refactor section N).

Because the body is thrown away, a generation whose POSE DRIFTED is still usable as
long as the head and shoulders held still.

Writes spritelab/faces_out/<key>__newface.png (the layer) and a review sheet.
"""
import sys, csv, pathlib
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from align import Reference

ROOT = pathlib.Path(__file__).resolve().parents[2]
ALIGNED = ROOT/"spritelab"/"aligned_expr"
FACES = ROOT/"spritelab"/"faces_out"
SHEETS = ROOT/"spritelab"/"sheets"
CHARS = ROOT/"normal_ST_Character_Folders"

def build(key, char, pose, outfit):
    ref = Reference.from_pose(str(CHARS/char/pose), outfit=outfit, anchor="body")
    al = Image.open(ALIGNED/f"{key}__aligned.png").convert("RGBA")
    fa = ref.face_alpha                                  # the shipped layer's own coverage
    new = np.asarray(al.convert("RGB")).copy()
    layer = np.dstack([new, fa]).astype(np.uint8)        # new pixels, original coverage
    FACES.mkdir(parents=True, exist_ok=True)
    Image.fromarray(layer, "RGBA").save(FACES/f"{key}__newface.png")

    outf = sorted((CHARS/char/pose/"outfits").glob("*.*"))
    body_p = next((p for p in outf if p.stem == outfit), outf[0])
    body = Image.open(body_p).convert("RGBA")
    panels = []
    for lbl, face in [("ORIGINAL", Image.open(sorted((CHARS/char/pose/"faces"/"face").glob("*.*"),
                        key=lambda p:(len(p.stem),p.stem))[0]).convert("RGBA")),
                      ("NEW EXPRESSION", Image.fromarray(layer, "RGBA"))]:
        c = body.copy(); c.alpha_composite(face, (0, 0))
        bg = Image.new("RGBA", c.size, (255,255,255,255)); bg.alpha_composite(c)
        panels.append((lbl, bg.convert("RGB")))
    x0,y0,x1,y1 = ref.box
    px,pt,pb = int((x1-x0)*0.6), int((y1-y0)*1.0), int((y1-y0)*1.1)
    cx0,cy0 = max(0,x0-px), max(0,y0-pt)
    cx1,cy1 = min(body.width,x1+px), min(body.height,y1+pb)
    return [(l, im.crop((cx0,cy0,cx1,cy1))) for l,im in panels]

def main():
    rows = [r for r in csv.DictReader(open(ROOT/"spritelab/results/expr.csv")) if r.get("char")]
    if len(sys.argv) > 1:
        rows = [r for r in rows if any(a in r["gen"] for a in sys.argv[1:])]
    cells = []
    for r in rows:
        key = pathlib.Path(r["gen"]).stem[:-len("_face")]
        try:
            cells.append((key, build(key, r["char"], r["pose"], r["outfit"]), float(r["body_pct"])))
            print(f"  {key}", flush=True)
        except Exception as e:
            print(f"  {key} FAILED {e}", flush=True)
    H = max(p[1].height for _,ps,_ in cells for p in ps)
    W = max(p[1].width  for _,ps,_ in cells for p in ps)
    PAD, LBL, TOP = 8, 15, 22
    cols = 4; rows_n = (len(cells)+cols-1)//cols
    cw = 2*W+6
    sheet = Image.new("RGB", (cols*(cw+PAD)+PAD, rows_n*(H+LBL+PAD)+PAD+TOP), (244,244,248))
    d = ImageDraw.Draw(sheet)
    d.text((PAD,6), "Each pair: ORIGINAL expression (left) | NEW generated expression (right), "
                    "both on the REAL untouched body", fill=(15,15,20))
    for i,(k,ps,bp) in enumerate(cells):
        px = PAD+(i%cols)*(cw+PAD); py = TOP+PAD+(i//cols)*(H+LBL+PAD)
        d.text((px,py+2), f"{k}   body {bp:.2f}%", fill=(30,30,38))
        for j,(l,im) in enumerate(ps):
            sheet.paste(im, (px+j*(W+6), py+LBL))
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEETS/"EXPR_new_faces_on_real_body.png")
    print(f"\n-> {SHEETS/'EXPR_new_faces_on_real_body.png'}  {sheet.size}")
    print(f"-> {len(cells)} new face layers in {FACES}")

if __name__ == "__main__":
    main()
