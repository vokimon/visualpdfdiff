import unittest
from io import BytesIO
import pypdf
from wand.image import Image
from wand.color import Color
from wand.drawing import Drawing
from .implementation import (
    build_diff_mask,
    side_by_side,
    overlay_image,
    overlay_page,
    highlightDifferences,
    centeredText,
    mask_paint,
    dilate,
)
import numpy as np

COLOR_MAP = {
    ".": (0, 0, 0),
    "R": (1, 0, 0),
    "G": (0, 1, 0),
    "B": (0, 0, 1),
    "W": (1, 1, 1),
    "Y": (1, 1, 0),
}


def lines(*lines):
    return "\n".join(lines)


def str_to_img(s):
    lines = s.split("\n")
    h, w = len(lines), len(lines[0])
    img = Image(width=w, height=h)
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            r, g, b = COLOR_MAP[ch]
            img[x, y] = Color(f"rgb({r*255:.0f},{g*255:.0f},{b*255:.0f})")
    return img


def img_to_str(img):
    rows = []
    for y in range(img.height):
        row = ""
        for x in range(img.width):
            px = img[x, y]
            if px.alpha < 0.01:
                row += "T"
            elif px.alpha < 0.99:
                row += "S"
            elif px.red > 0.8 and px.green < 0.2 and px.blue < 0.2:
                row += "R"
            elif px.blue > 0.8 and px.red < 0.2 and px.green < 0.2:
                row += "B"
            elif px.green > 0.8 and px.red < 0.2 and px.blue < 0.2:
                row += "G"
            elif px.red > 0.8 and px.green > 0.8 and px.blue > 0.8:
                row += "W"
            else:
                row += "."
        rows.append(row)
    return lines(*rows)


class TestDiffMask(unittest.TestCase):

    def test_identical_images(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG\nBW")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertEqual(img_to_str(diff), "..\n..")
        self.assertEqual(ndiffs, 0.0 / 4.0)

    def test_one_pixel_different(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG\nBY")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertAlmostEqual(ndiffs, 1.0 / 4.0)
        self.assertEqual(img_to_str(diff), "..\n.W")

    def test_different_sizes(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG.\nB..\n...")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertEqual(img_to_str(diff), "..W\n.WW\nWWW")
        self.assertAlmostEqual(ndiffs, 6.0 / 9.0)


class TestHighlightDifferences(unittest.TestCase):

    def test_single_pixel(self):
        with Image(width=7, height=7) as mask:
            mask[3, 3] = "white"
            highlightDifferences(mask, margin=1, edge_width=1)
            expected = lines(
                "SSSSSSS",
                "SRRRRRS",
                "SRTTTRS",
                "SRTTTRS",
                "SRTTTRS",
                "SRRRRRS",
                "SSSSSSS",
            )
            self.assertEqual(img_to_str(mask), expected)

    def test_wider_margin(self):
        with Image(width=9, height=9) as mask:
            mask[4, 4] = "white"
            highlightDifferences(mask, margin=2, edge_width=1)
            expected = lines(
                "SSSSSSSSS",
                "SRRRRRRRS",
                "SRTTTTTRS",
                "SRTTTTTRS",
                "SRTTTTTRS",
                "SRTTTTTRS",
                "SRTTTTTRS",
                "SRRRRRRRS",
                "SSSSSSSSS",
            )
            self.assertEqual(img_to_str(mask), expected)

    def test_wider_border(self):
        with Image(width=9, height=9) as mask:
            mask[4, 4] = "white"
            highlightDifferences(mask, margin=1, edge_width=2)
            expected = lines(
                "SSSSSSSSS",
                "SRRRRRRRS",
                "SRRRRRRRS",
                "SRRTTTRRS",
                "SRRTTTRRS",
                "SRRTTTRRS",
                "SRRRRRRRS",
                "SRRRRRRRS",
                "SSSSSSSSS",
            )
            self.assertEqual(img_to_str(mask), expected)


def _make_test_mask(w=4, h=4):
    mask = Image(width=w, height=h, background=Color("black"))
    with Drawing() as d:
        d.fill_color = Color("white")
        d.rectangle(w // 2 - 1, h // 2 - 1, 2, 2)
        d(mask)
    return mask


class TestMaskPaint(unittest.TestCase):
    def test_mask_paint_rgb(self):
        target = Image(width=4, height=4, background=Color("white"))
        target.alpha_channel = "set"
        target.alpha_channel = "remove"
        mask = _make_test_mask()
        mask_paint(target, mask, "rgba(255,0,0,1)")
        self.assertEqual(
            img_to_str(target),
            lines(
                "WWWW",
                "WRRW",
                "WRRW",
                "WWWW",
            ),
        )
        target.close()
        mask.close()

    def test_mask_paint_alpha(self):
        target = Image(width=4, height=4, background=Color("white"))
        target.alpha_channel = "set"
        target.alpha_channel = "remove"
        mask = _make_test_mask()
        mask_paint(target, mask, "rgba(1,1,0,0)")
        self.assertEqual(
            img_to_str(target),
            lines(
                "WWWW",
                "WTTW",
                "WTTW",
                "WWWW",
            ),
        )
        target.close()
        mask.close()


def make_page(r, g, b, w, h):
    from pypdf._page import PageObject
    from pypdf.generic import DecodedStreamObject, NameObject

    page = PageObject.create_blank_page(width=w, height=h)
    content = DecodedStreamObject()
    content.set_data(f"q {r} {g} {b} rg 0 0 {w} {h} re f Q".encode())
    page[NameObject("/Contents")] = content
    return page


def rasterize_page(page):
    writer = pypdf.PdfWriter()
    writer.add_page(page)
    buf = BytesIO()
    writer.write(buf)
    with Image(blob=buf.getvalue(), resolution=72) as img:
        img.background_color = "white"
        img.alpha_channel = "remove"
        img.format = "png"
        return Image(blob=img.make_blob())


class TestPdfPrimitives(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None

    def test_make_page_red(self):
        page = make_page(1, 0, 0, 50, 50)
        img = rasterize_page(page)
        self.assertEqual(img_to_str(img), ("R" * 50 + "\n") * 49 + "R" * 50)

    def test_make_page_blue(self):
        page = make_page(0, 0, 1, 50, 50)
        img = rasterize_page(page)
        self.assertEqual(img_to_str(img), ("B" * 50 + "\n") * 49 + "B" * 50)

    def test_sidebyside(self):
        red = make_page(1, 0, 0, 10, 10)
        blue = make_page(0, 0, 1, 10, 10)
        result = side_by_side(red, blue)
        img = rasterize_page(result)
        row = img_to_str(img)
        self.assertEqual(row, "\n".join(["R" * 10 + "B" * 10] * 10))

    def test_overlay_image(self):
        white = make_page(1, 1, 1, 20, 10)
        with Image(width=20, height=10, background=Color("red")) as img:
            result = overlay_image(white, img)
        raster = rasterize_page(result)
        self.assertEqual(img_to_str(raster), "\n".join(["R" * 20] * 10))

    def test_overlay_page(self):
        white = make_page(1, 1, 1, 4, 2)
        red = make_page(1, 0, 0, 2, 2)
        result = overlay_page(white, red, tx=2)
        img = rasterize_page(result)
        self.assertEqual(img_to_str(img), "\n".join(["W" * 2 + "R" * 2] * 2))


def boolarray2string(array):
    return "\n".join(["".join(["1" if x else "0" for x in row]) for row in array])


def string2boolarray(string):
    return np.array(
        [[0 if c == "0" else 1 for c in line] for line in string.split("\n")],
        dtype=bool,
    )


class TestDilate(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None

    def test_dilate_square_kernel_size_3(self):
        mask = string2boolarray(
            lines(
                "000000",
                "000000",
                "001000",
                "000000",
                "000000",
            )
        )

        result = dilate(mask, size=3, kernel="square")

        self.assertEqual(
            boolarray2string(result),
            lines(
                "000000",
                "011100",
                "011100",
                "011100",
                "000000",
            ),
        )

    def test_dilate_square_kernel_size_5(self):
        mask = string2boolarray(
            lines(
                "000000",
                "000000",
                "001000",
                "000000",
                "000000",
            )
        )

        result = dilate(mask, size=5, kernel="square")

        self.assertEqual(
            boolarray2string(result),
            lines(
                "111110",
                "111110",
                "111110",
                "111110",
                "111110",
            ),
        )


    def test_dilate_circle_kernel(self):
        mask = string2boolarray(lines(
            "0000000",
            "0000000",
            "0000000",
            "0001000",
            "0000000",
            "0000000",
            "0000000",
        ))
        result = dilate(mask, size=5, kernel="circle")
        self.assertEqual(boolarray2string(result), lines(
            "0000000",
            "0001000",
            "0011100",
            "0111110",
            "0011100",
            "0001000",
            "0000000",
        ))


if __name__ == "__main__":
    unittest.main()
