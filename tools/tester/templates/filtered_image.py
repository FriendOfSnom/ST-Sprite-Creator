import re

import renpy.display.im as im
import renpy.exports as renpy
from pymage_size import get_image_size
from renpy.display.motion import Transform
from renpy.exports import Displayable, store
from renpy.python import RevertableObject


def sanitize_filename_spaced(filename, prefix):
    return re.sub(rf"(^{re.escape(prefix)}/|\..+$)", "", filename).replace("/", " ")


class FilteredImage(Displayable):
    def __init__(self, child, **kwargs):
        super().__init__(**kwargs)
        if isinstance(child, str):
            self.name = sanitize_filename_spaced(child, "images")
            file = renpy.exports.file(child.replace("\\", "/"))
        else:
            self.name = sanitize_filename_spaced(child.image.filename, "images")
            file = renpy.exports.file(child.image.filename.replace("\\", "/"))
        self.child = renpy.easy.displayable(child)
        self.width, self.height = get_image_size(file).get_dimensions()

    def render(self, width, height, st, at):
        d = self.get_displayable()

        if store.screenfilter.blur > 0.0 and self.name != store.protagonist:
            ro = renpy.Render(self.width, self.height)
            d_blur = im.Blur(d, store.screenfilter.blur / 4.0)
            child_ro = renpy.render(d_blur, self.width, self.height, st, at)
            ro.blit(child_ro, (0, 0))
            return ro

        ro = renpy.render(d, self.width, self.height, st, at)

        if renpy.store.coordinate_grid_key_presses:
            point_size = (15, 15)
            dot = Transform(renpy.display.imagelike.Solid("#1E90FF"), maxsize=point_size)
            ro.place(
                dot,
                x=(width // 2) - (point_size[0] // 2),
                y=(height // 2) - (point_size[0] // 2),
                width=point_size[0],
                height=point_size[1],
            )

        return ro

    def per_interact(self):
        renpy.redraw(self, 0)

    def visit(self):
        return [self.child]

    def get_displayable(self):
        if store.screenfilter.colorblind:
            return store.screenfilter.tint(self.child)
        return self.child


class FilterProperties(RevertableObject):
    def __init__(self):
        self.colorblind = False
        self.blur = 0.0

    def tint(self, displayable):
        matrix = im.matrix.identity()
        if store.screenfilter.colorblind:
            # Simulate deuteranopia
            # https://github.com/HaxePunk/post-process/blob/master/assets/shaders/color/deuteranopia.frag
            matrix *= im.matrix(
                0.43,
                0.72,
                -0.15,
                0.0,
                0.0,
                0.34,
                0.57,
                0.09,
                0.0,
                0.0,
                -0.02,
                0.03,
                1.00,
                0.0,
                0.0,
                0.00,
                0.00,
                0.00,
                1.0,
                0.0,
            )
        return im.MatrixColor(displayable, matrix)

    def refresh(self):
        renpy.restart_interaction()


def init():
    store.screenfilter = FilterProperties()
