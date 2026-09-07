"""SpriteLab registration engine.

Puts an AI-generated image back into a real ST pose's coordinate space so it is
pixel-compatible with that character's existing face/expression layers.

Pure numpy + PIL. NO UI imports - this module is meant to drop into
shared/imaging/registration.py during the big refactor untouched.

Why each step exists (see memory: spritelab):
  * ST composites EVERY layer at the same origin, so a valid layer must occupy
    the same absolute pixel coords at the same scale, anchored top-left.
  * ST renders a pose mirrored whenever facing is left, which is the DEFAULT for
    the real game character folders (they have no `poses:` block). So a
    generation made from a game screenshot may be mirrored. We try both.
  * Gemini snaps output to fixed buckets. If it preserves the input aspect, the
    scale is known analytically and needs no search. If it does NOT (measured
    0.78% off on one run = 5.8px of drift), a single uniform scale cannot be
    right, so we also solve a small aspect correction.
  * Downscaling softens thin anime linework. The visible artifact is the
    crispness DISCONTINUITY at the face-layer boundary, so we sharpen to MATCH
    the reference, never to maximize.
"""
from __future__ import annotations

import dataclasses
import pathlib

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import binary_dilation, distance_transform_edt


# ----------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------
def on_white_gray(img: Image.Image) -> np.ndarray:
    """Composite over white and return float32 grayscale.

    Generations come back opaque-on-white, so putting the reference on white
    too keeps the two comparable.
    """
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img.convert("RGBA"))
    return np.asarray(bg.convert("L"), dtype=np.float32)


def edge_energy(gray: np.ndarray) -> float:
    """Mean gradient magnitude = how crisp the linework is."""
    gy, gx = np.gradient(gray)
    return float(np.hypot(gx, gy).mean())


def _ssd_map(img: np.ndarray, tmpl: np.ndarray):
    """Sum-of-squared-differences of `tmpl` at every position in `img`.

    FFT for the correlation term, an integral image for the window-energy term.
    Returns None if the template does not fit.
    """
    H, W = img.shape
    th, tw = tmpl.shape
    if th > H or tw > W:
        return None
    padded = np.zeros((H, W), np.float32)
    padded[:th, :tw] = tmpl[::-1, ::-1]          # correlation via convolution
    corr = np.fft.irfft2(np.fft.rfft2(img) * np.fft.rfft2(padded), s=(H, W))
    sq = np.cumsum(np.cumsum(img.astype(np.float64) ** 2, 0), 1)
    sq = np.pad(sq, ((1, 0), (1, 0)))
    win = sq[th:, tw:] - sq[:-th, tw:] - sq[th:, :-tw] + sq[:-th, :-tw]
    c = corr[th - 1:, tw - 1:][:win.shape[0], :win.shape[1]]
    return win - 2 * c + float((tmpl.astype(np.float64) ** 2).sum())


# ----------------------------------------------------------------------
# reference (the real ST pose we are aligning INTO)
# ----------------------------------------------------------------------
@dataclasses.dataclass
class Reference:
    size: tuple                 # (W, H) the target canvas
    gray: np.ndarray            # outfit+face composited, on white, gray
    rgb: np.ndarray             # same composite in RGB (needed for colour match)
    template: np.ndarray        # the INVARIANT patch we lock onto (face or body, see anchor)
    box: tuple                  # (x0,y0,x1,y1) FACE box, ALWAYS - colour fitting, the seam
                                # ring and the review crop all key off this, so it must not
                                # move when the anchor changes
    alpha: np.ndarray           # outfit+face alpha = where the CHARACTER actually is.
                                # Brightness cannot tell near-white skin from the white
                                # background; alpha can. See skin_mask().
    face_alpha: np.ndarray      # the FACE LAYER's alpha alone, on the full canvas. The
                                # colour fit hugs this boundary - it is the seam the eye
                                # judges, and the region ST composites the face over.
    template_box: tuple         # (x0,y0,x1,y1) where `template` came from. Equals `box`
                                # when anchor="face"; a torso band when anchor="body".

    @classmethod
    def from_pose(cls, pose_dir, outfit: str | None = None, face: str = "0",
                  skip_top: float = 0.30, anchor: str = "face") -> "Reference":
        """Build from a real character pose folder.

        skip_top drops the upper part of the face box because hats and hair
        legitimately change; eyes/nose/mouth/jaw do not.

        `anchor` picks the INVARIANT - the region that must not have moved, which is
        what we lock onto. It is always the thing we are NOT generating:
          "face" - for OUTFIT generation. The outfit changes, the face does not.
          "body" - for EXPRESSION generation. The face changes, the body does not, so
                   locking onto the face would be locking onto the one thing that moved.
                   Uses a band of torso below the face box (shoulders/collar/chest),
                   which is high-contrast and stable.
        """
        pose_dir = pathlib.Path(pose_dir)
        outfits = sorted((pose_dir / "outfits").glob("*.*"))
        body_p = next((p for p in outfits if p.stem == outfit), outfits[0])
        faces = sorted((pose_dir / "faces" / "face").glob("*.*"))
        face_p = next((p for p in faces if p.stem == face), faces[0])

        body = Image.open(body_p).convert("RGBA")
        face_img = Image.open(face_p).convert("RGBA")
        comp = body.copy()
        comp.alpha_composite(face_img, (0, 0))       # ST: same origin
        gray = on_white_gray(comp)

        alpha = np.asarray(face_img)[..., 3]
        ys, xs = np.nonzero(alpha > 16)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y_top, y1 = int(ys.min()), int(ys.max()) + 1
        y0 = int(y_top + skip_top * (y1 - y_top))
        box = (x0, y0, x1, y1)
        if anchor == "body":
            fh = y1 - y0
            ca = np.asarray(comp)[..., 3]
            by0 = min(comp.size[1] - 2, y1 + int(fh * 0.15))       # clear of the jaw
            by1 = min(comp.size[1], by0 + int(fh * 2.2))
            rows = np.nonzero((ca[by0:by1] > 16).any(1))[0]
            cols = np.nonzero((ca[by0:by1] > 16).any(0))[0]
            if len(rows) > 8 and len(cols) > 8:
                box = (int(cols.min()), by0 + int(rows.min()),
                       int(cols.max()) + 1, by0 + int(rows.max()) + 1)
        elif anchor != "face":
            raise ValueError(f"unknown anchor {anchor!r}")
        bg = Image.new("RGBA", comp.size, (255, 255, 255, 255))
        bg.alpha_composite(comp)
        rgb = np.asarray(bg.convert("RGB"), dtype=np.float32)
        comp_a = np.asarray(comp)[..., 3]
        fa = Image.new("RGBA", comp.size, (0, 0, 0, 0))
        fa.alpha_composite(face_img, (0, 0))
        bx0, by0_, bx1, by1_ = box
        return cls(body.size, gray, rgb, gray[by0_:by1_, bx0:bx1], (x0, y0, x1, y1),
                   comp_a, np.asarray(fa)[..., 3], box)


# ----------------------------------------------------------------------
# the transform we solve for
# ----------------------------------------------------------------------
@dataclasses.dataclass
class Transform:
    mirrored: bool
    sx: float                   # horizontal scale applied to the candidate
    sy: float                   # vertical scale (differs from sx if Gemini distorted)
    dx: int
    dy: int
    score: float                # mean SSD per pixel; lower is better
    analytic: bool              # True if the winning scale came from matching aspect ratios
    hit_rail: bool = False      # True if the solution sits at the edge of scale_range,
                                # which means "no fit was found", not "the fit is 1.6"

    def describe(self) -> str:
        kind = "analytic" if self.analytic else "searched"
        agree = "uniform" if abs(self.sx - self.sy) < 1e-6 else f"sx!=sy ({self.sx:.5f}/{self.sy:.5f})"
        return (f"{'mirrored' if self.mirrored else 'upright'}, {kind} scale "
                f"{self.sx:.5f} ({agree}), shift ({self.dx},{self.dy}), score {self.score:.0f}")


def _best_at(cand: Image.Image, sx: float, sy: float, tmpl: np.ndarray):
    """Best SSD of `tmpl` over `cand` scaled by (sx, sy). Returns (score, px, py).

    `tmpl` is passed explicitly rather than taken from a Reference so the coarse
    passes can hand in a DECIMATED template (see find_transform).
    """
    nw, nh = max(1, int(round(cand.width * sx))), max(1, int(round(cand.height * sy)))
    gray = on_white_gray(cand.resize((nw, nh), Image.LANCZOS))
    m = _ssd_map(gray, tmpl)
    if m is None:
        return None
    idx = int(np.argmin(m))
    py, px = np.unravel_index(idx, m.shape)
    return float(m[py, px]) / tmpl.size, int(px), int(py)


def _decimate_tmpl(tmpl: np.ndarray, d: int) -> np.ndarray:
    if d == 1:
        return tmpl
    h, w = tmpl.shape
    small = Image.fromarray(tmpl).resize((max(1, w // d), max(1, h // d)), Image.BILINEAR)
    return np.asarray(small, dtype=np.float32)


def _decimate_img(im: Image.Image, d: int) -> Image.Image:
    if d == 1:
        return im
    return im.resize((max(1, im.width // d), max(1, im.height // d)), Image.LANCZOS)


def find_transform(candidate: Image.Image, ref: Reference,
                   scale_range=(0.25, 1.60), coarse_step=0.01,
                   aspect_search=True) -> Transform:
    """Solve mirror + scale + translation that maps `candidate` into ref space."""
    tw, th = ref.size
    x0, y0, _, _ = ref.template_box
    best: Transform | None = None

    for mirrored in (False, True):
        cand = candidate.transpose(Image.FLIP_LEFT_RIGHT) if mirrored else candidate

        # An aspect match makes the corner-to-corner scale exactly computable, but
        # ONLY if the FRAMING also matches. It often does not: Gemini returns a
        # full-body shot in the same shape rectangle as a thigh-up reference, and
        # then tw/cand.width is badly wrong (measured on tori_a_full_body: it gave
        # 0.547 and 36.9% face error, where the true scale was 0.93 / 2.7%).
        # So this is now just ONE MORE CANDIDATE, never a short circuit.
        seeds = []
        if abs(cand.width / cand.height - tw / th) < 5e-4:
            seeds.append(tw / cand.width)

        # ---- pass 1: coarse sweep at 1/4 resolution (16x cheaper per evaluation)
        lo = _decimate_img(cand, 4)
        tl = _decimate_tmpl(ref.template, 4)
        grid = []
        k = scale_range[0]
        while k <= scale_range[1] + 1e-9:
            got = _best_at(lo, k, k, tl)
            if got:
                grid.append((got[0], k))
            k += coarse_step
        if not grid:
            continue
        grid.sort()
        # keep the two best basins (plus any analytic seed) - a 1/4-res winner can
        # be one basin off, and refining two costs almost nothing now
        cands = [g[1] for g in grid[:2]] + seeds

        # ---- pass 2: refine scale + aspect at 1/2 resolution
        md = _decimate_img(cand, 2)
        mt = _decimate_tmpl(ref.template, 2)
        ratios = np.arange(0.98, 1.0201, 0.004) if aspect_search else [1.0]
        mid = None
        for k0 in cands:
            for kk in np.arange(k0 - coarse_step, k0 + coarse_step + 1e-9, coarse_step / 2.5):
                for r in ratios:
                    got = _best_at(md, kk, kk * r, mt)
                    if got and (mid is None or got[0] < mid[0]):
                        mid = (got[0], float(kk), float(r))
        if mid is None:
            continue
        _, k, kr = mid

        # ---- pass 3: polish at full resolution, tight window
        fine = None
        for kk in np.arange(k - coarse_step / 2.5, k + coarse_step / 2.5 + 1e-9, coarse_step / 5):
            for r in np.arange(kr - 0.004, kr + 0.0041, 0.002) if aspect_search else [1.0]:
                got = _best_at(cand, kk, kk * r, ref.template)
                if got and (fine is None or got[0] < fine[0]):
                    fine = (got[0], float(kk), float(r), got[1], got[2])
        if fine is None:
            continue
        s, k, kr, px, py = fine

        rail = min(abs(k - scale_range[0]), abs(k - scale_range[1])) < coarse_step * 1.5
        t = Transform(mirrored, k, k * kr, x0 - px, y0 - py, s,
                      analytic=bool(seeds) and abs(k - seeds[0]) < 1e-6,
                      hit_rail=rail)
        if best is None or t.score < best.score:
            best = t

    assert best is not None, "no usable transform found"
    return best


def apply_transform(candidate: Image.Image, t: Transform, ref: Reference) -> Image.Image:
    """Resample ONCE at the final transform and lay it on the target canvas."""
    cand = candidate.transpose(Image.FLIP_LEFT_RIGHT) if t.mirrored else candidate
    nw = max(1, int(round(cand.width * t.sx)))
    nh = max(1, int(round(cand.height * t.sy)))
    out = Image.new("RGBA", ref.size, (255, 255, 255, 255))
    out.paste(cand.resize((nw, nh), Image.LANCZOS), (t.dx, t.dy))
    return out


def match_crispness(aligned: Image.Image, ref: Reference,
                    radius: float = 1.1, threshold: int = 2) -> tuple:
    """Sharpen only as much as it takes to MATCH the reference's linework.

    Overshooting makes the face-layer seam more visible, not less, so we aim at
    the reference rather than at maximum sharpness. The right amount varies by
    character, art style and downscale factor, so it is measured every run.
    """
    x0, y0, x1, y1 = ref.box
    target = edge_energy(ref.gray[y0:y1, x0:x1])
    best = (0, None, 1e9)
    for pct in range(0, 141, 5):
        img = aligned if pct == 0 else aligned.filter(
            ImageFilter.UnsharpMask(radius=radius, percent=pct, threshold=threshold))
        got = edge_energy(on_white_gray(img)[y0:y1, x0:x1])
        if abs(got - target) < best[2]:
            best = (pct, img, abs(got - target))
    return best[0], best[1], target


def residual(aligned: Image.Image, ref: Reference, shrink: float = 1.0) -> tuple:
    """How well the invariant region matches, as (mean_abs, percent_over_25).

    `shrink` narrows the measured box toward its centre. This matters a lot:
    the full face box includes hair, which the AI legitimately redraws, so it
    reports big numbers even when the alignment is perfect. Measured on three
    good alignments (full box -> central 30%):
        tori_a 3.97% -> 0.15%,  zoey_b 6.14% -> 0.46%,  zoey_a 14.82% -> 2.65%
    So use a TIGHT box (see `gate`) to judge alignment, and the full box only
    for crispness matching, where the extra context helps.
    """
    x0, y0, x1, y1 = ref.box
    if shrink < 1.0:
        w, h = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        x0, x1 = int(cx - w * shrink / 2), int(cx + w * shrink / 2)
        y0, y1 = int(cy - h * shrink / 2), int(cy + h * shrink / 2)
    got = on_white_gray(aligned)[y0:y1, x0:x1]
    d = np.abs(got - ref.gray[y0:y1, x0:x1])
    return float(d.mean()), float((d > 25).mean() * 100.0)


def gate(aligned: Image.Image, ref: Reference, max_pct: float = 5.0) -> tuple:
    """Verification gate: measure the CENTRAL face (eyes/nose/mouth), which is
    the part the AI must not have moved. Returns (ok, percent).

    NOT SUFFICIENT ON ITS OWN - see verify(). A totally failed alignment can
    still pass this if the small central window happens to land on flat skin in
    both images (tori_c aligned to just an arm and scored 1.95%).
    """
    _, pct = residual(aligned, ref, shrink=0.30)
    return pct <= max_pct, pct


MAX_FRAME_PCT = 25.0       # whole-frame disagreement; clothing legitimately differs,
                           # but a real alignment stays well under this
MAX_FACE_PCT = 5.0


def verify(aligned: Image.Image, ref: Reference, t: Transform | None = None,
           max_face: float = MAX_FACE_PCT, max_frame: float = MAX_FRAME_PCT) -> tuple:
    """Full alignment check. Returns (ok, reasons).

    Three independent signals, because each one alone can be fooled:
      * face_pct  - the central face must not have moved. Can be fooled by flat
                    regions, so it is necessary but not sufficient.
      * frame_pct - catches the case where the face window got lucky but the
                    whole registration is wrong (tori_c: face 1.95%, frame 39%).
      * hit_rail  - the scale search ran to the edge of its range, which means
                    "no fit found" rather than a genuine extreme scale
                    (tori_c solved at sx=1.598 against a rail of 1.60).
    """
    reasons = []
    _, face_pct = residual(aligned, ref, shrink=0.30)
    _, frame_pct = residual(aligned, ref, shrink=1.0)
    if face_pct > max_face:
        reasons.append(f"face {face_pct:.2f}% > {max_face}%")
    if frame_pct > max_frame:
        reasons.append(f"frame {frame_pct:.2f}% > {max_frame}%")
    if t is not None and t.hit_rail:
        reasons.append(f"scale {t.sx:.3f} hit the search rail (no fit found)")
    return (not reasons), reasons


def register(candidate_path, pose_dir, outfit=None, face="0"):
    """Convenience: solve, apply, crispness-match, and report."""
    ref = Reference.from_pose(pose_dir, outfit=outfit, face=face)
    cand = Image.open(candidate_path).convert("RGBA")
    t = find_transform(cand, ref)
    aligned = apply_transform(cand, t, ref)
    pct, sharpened, target = match_crispness(aligned, ref)
    return ref, t, aligned, sharpened, pct, residual(aligned, ref), residual(sharpened, ref)


def color_match(aligned: Image.Image, ref: Reference, mode: str = "feather",
                alpha: np.ndarray | None = None) -> tuple:
    """Correct the AI's colour cast. Returns (image, coef) - coef None means NOT corrected.

    `alpha` is the CHARACTER mask for the aligned image, from background removal, and
    should be supplied: generations arrive opaque-on-white, and pure white is only 21.8
    from ST's pale skin (255,249,234) - inside BODY_SKIN_TOL - so without it a pale
    character's BACKGROUND is treated as her face. Falls back to a crude guess if None.

    Modes, and the evidence for the default (held-out means over 14-15 generations,
    lower better; user confirmed by eye at 150% zoom):

                     none   chest    ring  feather  clusters
        SKIN error   8.32    7.43    5.98     5.88      7.53
        HAIR error   9.48   19.04   14.44    12.51      4.89

      "feather"  DEFAULT. Fit the offset on generated skin in a RING hugging the face
                 layer - the seam the eye actually judges - then apply it with a weight
                 that decays with distance from that boundary. Beats every alternative
                 on skin and limits how far a skin-fitted offset gets smeared over hair.
      "hair"     feather PLUS a paired hair offset applied to HAIR ONLY (selected by
                 colour, never by a y cut-off, which would draw a line across long hair).
                 Opt-in: it clearly won on sayaka and clearly lost on anuja/tori/kiyoshi,
                 and no measurable discriminator separated those cases on 15 samples.
      "body"     legacy: fit on chest skin, apply globally.
      "offset"   legacy: fit inside the face box - the region ST covers with the real
                 expression. WORSE THAN NO CORRECTION. Kept only for comparison.
      "gain"     legacy: also fits a multiplier.
    """
    A = _rgb_on_white(aligned)
    R = _rgb_on_white_arr(ref)
    x0, y0, x1, y1 = ref.box
    Rb, Ab = R[y0:y1, x0:x1], A[y0:y1, x0:x1]
    skin, tone = skin_mask(Rb, alpha=ref.alpha[y0:y1, x0:x1])
    if int(skin.sum()) < MIN_SKIN_PX or tone is None:
        return aligned, None
    target = Rb[skin].mean(0)

    body = ref.alpha > 200
    character = body | (A.max(2) < 250) if alpha is None else (alpha > 200)
    gen_skin = (np.linalg.norm(A - tone, axis=2) < BODY_SKIN_TOL) & character

    if mode in ("feather", "hair"):
        covered = ref.face_alpha > 200
        ring = binary_dilation(covered, np.ones((9, 9))) & ~covered & body & gen_skin
        if int(ring.sum()) < 300:
            return aligned, None
        off = target - A[ring].mean(0)
        if float(np.linalg.norm(off)) > MAX_SANE_OFFSET:
            return aligned, None
        w = np.exp(-distance_transform_edt(~covered)
                   / max(8.0, (y1 - y0) * 0.9)).astype(np.float32) * character
        out = A + off * (w * gen_skin)[..., None]
        if mode == "hair":
            fh = y1 - y0
            band = np.zeros(A.shape[:2], bool)
            band[max(0, int(y0 - fh * 1.4)):min(A.shape[0], int(y1 + fh * 0.35)), :] = True
            gen_other = character & ~gen_skin
            mh = band & body & ~covered & ~(np.linalg.norm(R - tone, axis=2) < BODY_SKIN_TOL)
            if int(mh.sum()) >= 300 and int((gen_other & band).sum()) >= 100:
                oh = (R[mh] - A[mh]).mean(0)
                if float(np.linalg.norm(oh)) <= MAX_SANE_OFFSET:
                    # HAIR ONLY. Applying this to every non-skin pixel recolours the
                    # outfit Gemini invented - measured 66-86% of those pixels are
                    # clothing, and that is what made this lose everywhere but sayaka.
                    ht = np.median(A[gen_other & band], axis=0)
                    hair = (np.linalg.norm(A - ht, axis=2) < HAIR_TOL) & gen_other
                    out = out + oh * (w * hair)[..., None]
        out = np.clip(out, 0, 255)
        return Image.fromarray(out.astype(np.uint8)).convert("RGBA"), [(1.0, float(o)) for o in off]

    if mode == "body":
        m = gen_skin & body
        m[:y1, :] = False
        off = target - A[m].mean(0) if int(m.sum()) >= MIN_SKIN_PX else (Rb[skin] - Ab[skin]).mean(0)
    elif mode == "gain":
        out = A.copy()
        coef = []
        for c in range(3):
            M = np.stack([Ab[skin][:, c], np.ones(int(skin.sum()))], 1)
            g, b = np.linalg.lstsq(M, Rb[skin][:, c], rcond=None)[0]
            coef.append((float(g), float(b)))
            out[..., c] = np.clip(A[..., c] * g + b, 0, 255)
        return Image.fromarray(out.astype(np.uint8)).convert("RGBA"), coef
    else:
        off = (Rb[skin] - Ab[skin]).mean(0)

    if float(np.linalg.norm(off)) > MAX_SANE_OFFSET:
        return aligned, None
    out = np.clip(A + off * character[..., None], 0, 255)
    return Image.fromarray(out.astype(np.uint8)).convert("RGBA"), [(1.0, float(o)) for o in off]


def _rgb_on_white(img: Image.Image) -> np.ndarray:
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img.convert("RGBA"))
    return np.asarray(bg.convert("RGB"), dtype=np.float32)


def _rgb_on_white_arr(ref: Reference) -> np.ndarray:
    """Reference RGB, rebuilt from its stored grayscale source path is not kept,
    so callers pass a Reference built by from_pose which retains `rgb`."""
    return ref.rgb


# ----------------------------------------------------------------------
# skin detection + colour gate
# ----------------------------------------------------------------------
MIN_SKIN_PX = 200          # below this the colour fit is not trustworthy
MAX_SANE_OFFSET = 25.0     # real corrections measured 4-9; far above = something is wrong
BODY_SKIN_TOL = 45.0       # colour ball for finding bare skin on the generated body
HAIR_TOL = 70.0            # colour ball around the fitted hair tone (mode="hair")
CONTINUOUS_TOL = 30.0      # max colour jump for a column to count as 'the same material
                           # continues across the neck cut' (color_match_head)


def skin_mask(face_box_rgb: np.ndarray, tol: float = 40.0, alpha: np.ndarray | None = None):
    """Find skin in a face crop, WITHOUT assuming a skin tone.

    Learn the tone GEOMETRICALLY first (the lower-centre of a face box is the
    cheek, which is skin for essentially any anime character), then expand by
    colour similarity to gather enough pixels.

    Why not the obvious alternatives - both were tried and both failed:
      * brightness heuristic (max>170 ...): finds only 1.8% of anuja (dark skin)
        and is knife-edge sensitive - moving its upper bound 255 -> 253 swung
        tori's fitted offset from +3.7 to +14.0.
      * dominant colour cluster: picks HAIR on hair-heavy faces - john's black
        (42,42,42), flavia's blonde, sayaka's pink.
    Cheek-anchoring gave a plausible warm tone for all 9 test characters,
    correctly reading anuja as (225,168,140) vs pale (253,244,221).
    """
    h, w = face_box_rgb.shape[:2]
    ys, xs = slice(int(h * 0.55), int(h * 0.88)), slice(int(w * 0.35), int(w * 0.65))
    cheek = face_box_rgb[ys, xs]
    if alpha is not None:
        # Alpha is exact. The old brightness guard (max < 254) was meant to drop the
        # white BACKGROUND, but pale ST skin highlights reach 254-255, so it threw away
        # 88-99% of the real skin on irene/john/sayaka/flavia/kiyoshi and left only
        # SHADOW pixels - irene_a then "learned" (235,160,152) and tinted her whole
        # body pink. Measured: irene_b found 0 skin px, anuja 2968.
        ok_cheek = alpha[ys, xs] > 200
        ok_all = alpha > 200
    else:
        ok_cheek = (cheek.max(2) < 254) & (cheek.max(2) > 25)
        ok_all = (face_box_rgb.max(2) < 254)
    v = cheek[ok_cheek & (cheek.max(2) > 25)]
    if len(v) < 30:
        return np.zeros(face_box_rgb.shape[:2], bool), None
    tone = np.median(v, axis=0)
    d = np.linalg.norm(face_box_rgb - tone, axis=2)
    return (d < tol) & ok_all, tone


def tone_is_plausible(tone) -> bool:
    """Skin should be warm (R >= G >= B) and not near-black. A failure here means
    the cheek sample hit hair or an occlusion, so the correction is untrustworthy."""
    if tone is None:
        return False
    return bool(tone[0] >= tone[1] >= tone[2] - 6 and tone[0] > 90)


def color_gate(aligned: Image.Image, ref: Reference, coef) -> tuple:
    """Validate the colour correction. Returns (status, detail).

    status: "ok" | "insufficient" | "suspect"

    Deliberately NOT a single pass/fail number, because the one genuinely
    independent test (comparing skin above vs below the face-layer seam) is only
    available when bare skin exists on BOTH sides. It worked on zoey
    (10.25 -> 1.38 and 13.43 -> 3.04, below her own reference baseline) but is
    meaningless on tori, whose neck is covered by a collar. So: always run the
    universal checks, run the seam check only when the data supports it, and say
    "insufficient" rather than guessing.
    """
    x0, y0, x1, y1 = ref.box
    skin, tone = skin_mask(ref.rgb[y0:y1, x0:x1], alpha=ref.alpha[y0:y1, x0:x1])
    n = int(skin.sum())
    if coef is None or n < MIN_SKIN_PX:
        return "insufficient", f"only {n} skin px (need {MIN_SKIN_PX}); NOT colour corrected"
    if not tone_is_plausible(tone):
        return "suspect", f"learned tone {tone} is not plausible skin (cheek sample hit hair?)"
    mag = max(abs(b) for _, b in coef)
    if mag > MAX_SANE_OFFSET:
        return "suspect", f"correction {mag:.1f} exceeds sane range {MAX_SANE_OFFSET}"
    return "ok", f"tone {tuple(int(t) for t in tone)}, n={n}, max offset {mag:.1f}"


# ----------------------------------------------------------------------
# EXPRESSION-side colour: correct a harvested HEAD to match the real body
# ----------------------------------------------------------------------
def color_match_head(head: Image.Image, ref: Reference, band: int = 6) -> tuple:
    """Correct a whole-head expression layer so it joins the real body invisibly.

    Returns (corrected RGBA, info dict).

    THE OBJECTIVE IS THE SEAM, NOT THE MEAN. An earlier version fitted the head's
    overall skin mean to the body's overall skin mean and applied that globally. It made
    every result WORSE: the neck just above the cut and the neck just below are the same
    anatomy under the same light and were already nearly matched, so a global offset
    pushed them apart and drew a hard horizontal LINE across the chest at the cut - the
    one defect a viewer can actually see.

    So: fit the offset ACROSS THE CUT and apply it uniformly to the whole head.
      * PER-COLUMN PAIRING. For each column, average the few rows just above the cut and
        the few just below, and difference them. Columns are anatomically continuous, so
        this compares like with like (chin over collar, hair over hair) without having to
        classify materials at all - which also sidesteps the "is this skin or a white
        shirt" problem entirely.
      * UNIFORM over the head, not feathered: the head is one generated image and is
        already internally consistent, so a single offset removes the seam without
        introducing a gradient inside the face.
    """
    # Use the layer's OWN RGB. _rgb_on_white() would flatten every semi-transparent
    # pixel against WHITE, and re-attaching the original alpha then composites that over
    # the body a SECOND time - double-blending. That put a light halo along the whole
    # feathered neck band and around every antialiased hair edge, which is precisely the
    # line the user saw appear only in the corrected versions.
    A = np.asarray(head.convert("RGBA"))[..., :3].astype(np.float32)
    a = np.asarray(head)[..., 3]
    R = ref.rgb
    info = {"offset": None, "columns": 0}

    rows = np.nonzero((a > 200).any(1))[0]
    if not len(rows):
        return head, info
    ny = int(rows.max()) + 1

    hi0, hi1 = max(0, ny - band), max(1, ny)                 # inside the head layer
    lo0, lo1 = min(A.shape[0] - 1, ny + 1), min(A.shape[0], ny + 1 + band)
    up_ok = a[hi0:hi1] > 200
    dn_ok = ref.alpha[lo0:lo1] > 200

    diffs = []
    for x in range(A.shape[1]):
        u, d = up_ok[:, x], dn_ok[:, x]
        if u.sum() >= 2 and d.sum() >= 2:
            diffs.append(R[lo0:lo1, x][d].mean(0) - A[hi0:hi1, x][u].mean(0))
    if len(diffs) < 20:
        return head, info
    D = np.stack(diffs)

    # Keep only columns where the MATERIAL IS CONTINUOUS across the cut. The neck is the
    # narrowest row, which is geometrically the right place to cut - but it is often
    # exactly the collar line, so many columns compare bare neck against a navy vest and
    # differ by 80+. Those are not a seam to fix: a material change already hides the
    # join with its own hard edge. A visible seam only exists where the same material
    # continues across the cut, so fit on those columns alone.
    keep = np.linalg.norm(D, axis=1) < CONTINUOUS_TOL
    if int(keep.sum()) < 20:
        return head, info                    # nothing continuous crosses the cut: no seam
    off = np.median(D[keep], axis=0)
    if float(np.linalg.norm(off)) > MAX_SANE_OFFSET:
        return head, info

    # Weight the offset by the layer's OWN ALPHA so the correction fades out exactly as
    # the head does. Applying it at full strength through the feathered rows fights the
    # alpha blend and puts a step at BOTH ends of the fade - measured on irene_a, the
    # row-to-row jump went 13-18 (uncorrected) to 42-50 (corrected), one spike at the cut
    # and another exactly FEATHER rows below it.
    out = np.clip(A + off * (a[..., None] / 255.0), 0, 255)
    info["offset"] = off
    info["columns"] = int(keep.sum())
    return Image.fromarray(np.dstack([out, a]).astype(np.uint8), "RGBA"), info
