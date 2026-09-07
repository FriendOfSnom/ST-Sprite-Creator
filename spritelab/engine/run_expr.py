"""Register EXPRESSION generations back into their real pose (section N harness).

Mirror image of run_batch.py. There the outfit was generated and the FACE was the
invariant; here the face is generated and the BODY is the invariant, so the reference
is built with anchor="body". Everything else - transform search, background removal,
colour, verification - is reused unchanged.

Usage:  python3 spritelab/engine/run_expr.py [name_filter ...]
"""
import io, sys, csv, time, pathlib, traceback
import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import align
from align import Reference, find_transform, apply_transform, residual, on_white_gray, edge_energy

ROOT = pathlib.Path(__file__).resolve().parents[2]
IN, OUT = ROOT/"spritelab"/"inputs", ROOT/"spritelab"/"outputs"
ALIGNED, RESULTS = ROOT/"spritelab"/"aligned_expr", ROOT/"spritelab"/"results"
CHARS = ROOT/"normal_ST_Character_Folders"

F = ["gen","char","pose","outfit","ref_w","ref_h","gen_w","gen_h","mirrored","hit_rail",
     "sx","sy","dx","dy","score","body_pct","body_mean","frame_pct","crisp_pct",
     "cutoff_pct","secs","note"]

def main():
    gens = sorted(OUT.glob("*_face.png"))
    if len(sys.argv) > 1:
        gens = [g for g in gens if any(a in g.name for a in sys.argv[1:])]
    RESULTS.mkdir(parents=True, exist_ok=True); ALIGNED.mkdir(parents=True, exist_ok=True)
    with (RESULTS/"expr.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=F); w.writeheader(); fh.flush()
        for i, g in enumerate(gens, 1):
            key = g.stem[:-len("_face")]
            parts = key.split("_"); char, pose, outfit = parts[0], parts[1], "_".join(parts[2:])
            print(f"[{i}/{len(gens)}] {g.name}", flush=True)
            try:
                ref = Reference.from_pose(str(CHARS/char/pose), outfit=outfit, anchor="body")
                cand = Image.open(g).convert("RGBA")
                t0 = time.time(); t = find_transform(cand, ref); al = apply_transform(cand, t, ref)
                secs = time.time()-t0
                al.save(ALIGNED/f"{key}__aligned.png")
                # score the BODY band (the invariant) instead of the face
                bx0, by0, bx1, by1 = ref.template_box
                got = on_white_gray(al)[by0:by1, bx0:bx1]
                d = np.abs(got - ref.gray[by0:by1, bx0:bx1])
                bmean, bpct = float(d.mean()), float((d > 25).mean()*100)
                _, fpct = residual(al, ref, shrink=1.0)
                crisp = 100*edge_energy(on_white_gray(al))/edge_energy(ref.gray)
                sw, sh = cand.width*t.sx, cand.height*t.sy
                ox = max(0.0, min(t.dx+sw, ref.size[0]) - max(t.dx, 0.0))
                oy = max(0.0, min(t.dy+sh, ref.size[1]) - max(t.dy, 0.0))
                cut = 100*(1 - (ox*oy)/(sw*sh))
                row = dict(gen=g.name, char=char, pose=pose, outfit=outfit,
                           ref_w=ref.size[0], ref_h=ref.size[1], gen_w=cand.width, gen_h=cand.height,
                           mirrored=t.mirrored, hit_rail=t.hit_rail, sx=round(t.sx,5), sy=round(t.sy,5),
                           dx=t.dx, dy=t.dy, score=round(t.score,1),
                           body_pct=round(bpct,2), body_mean=round(bmean,2),
                           frame_pct=round(fpct,2), crisp_pct=round(crisp,1),
                           cutoff_pct=round(cut,1), secs=round(secs,1), note="")
            except Exception as e:
                traceback.print_exc(); w.writerow({"gen": g.name, "note": f"ERROR {e}"}); fh.flush(); continue
            w.writerow(row); fh.flush()
            print(f"        {row['secs']:5.1f}s  BODY {row['body_pct']:5.2f}%  frame {row['frame_pct']:5.2f}%  "
                  f"crisp {row['crisp_pct']:5.1f}%  cutoff {row['cutoff_pct']:5.1f}%  "
                  f"mirror={row['mirrored']} sx={row['sx']}", flush=True)
    print(f"\nwrote {RESULTS/'expr.csv'}", flush=True)

if __name__ == "__main__":
    main()
