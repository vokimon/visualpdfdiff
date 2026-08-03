import unittest
from io import BytesIO
import pypdf
from wand.image import Image
from wand.color import Color
from visualpdfdiff.diff import (
    build_diff_mask,
    side_by_side,
    overlay_image,
    highlightDifferences,
    centeredText,
)

COLOR_MAP = {
    '.': (0, 0, 0),
    'R': (1, 0, 0),
    'G': (0, 1, 0),
    'B': (0, 0, 1),
    'W': (1, 1, 1),
    'Y': (1, 1, 0),
}


def str_to_img(s):
    lines = s.split('\n')
    h, w = len(lines), len(lines[0])
    img = Image(width=w, height=h)
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            r, g, b = COLOR_MAP[ch]
            img[x, y] = Color(f'rgb({r*255:.0f},{g*255:.0f},{b*255:.0f})')
    return img


def img_to_str(img):
    rows = []
    for y in range(img.height):
        row = ''
        for x in range(img.width):
            px = img[x, y]
            if px.alpha < 0.01:
                row += 'T'
            elif px.alpha < 0.99:
                row += 'S'
            elif px.red > 0.8 and px.green < 0.2 and px.blue < 0.2:
                row += 'R'
            elif px.blue > 0.8 and px.red < 0.2 and px.green < 0.2:
                row += 'B'
            elif px.green > 0.8 and px.red < 0.2 and px.blue < 0.2:
                row += 'G'
            elif px.red > 0.8 and px.green > 0.8 and px.blue > 0.8:
                row += 'W'
            else:
                row += '.'
        rows.append(row)
    return '\n'.join(rows)


class TestDiffMask(unittest.TestCase):

    def test_identical_images(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG\nBW")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertEqual(img_to_str(diff), '..\n..')
        self.assertEqual(ndiffs, 0.0/4.0)

    def test_one_pixel_different(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG\nBY")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertAlmostEqual(ndiffs, 1.0/4.0)
        self.assertEqual(img_to_str(diff), '..\n.W')

    def test_different_sizes(self):
        a = str_to_img("RG\nBW")
        b = str_to_img("RG.\nB..\n...")
        diff, ndiffs = build_diff_mask(a, b)
        self.assertEqual(img_to_str(diff), '..W\n.WW\nWWW')
        self.assertAlmostEqual(ndiffs, 6.0/9.0)


class TestHighlightDifferences(unittest.TestCase):

    def test_single_pixel(self):
        with Image(width=7, height=7) as mask:
            mask[3, 3] = 'white'
            highlightDifferences(mask, margin=1, edge_width=1)
            expected = (
                "SSSSSSS\n"
                "SRRRRRS\n"
                "SRTTTRS\n"
                "SRTTTRS\n"
                "SRTTTRS\n"
                "SRRRRRS\n"
                "SSSSSSS"
            )
            self.assertEqual(img_to_str(mask), expected)

    def test_wider_margin(self):
        with Image(width=9, height=9) as mask:
            mask[4, 4] = 'white'
            highlightDifferences(mask, margin=2, edge_width=1)
            expected = (
                "SSSSSSSSS\n"
                "SRRRRRRRS\n"
                "SRTTTTTRS\n"
                "SRTTTTTRS\n"
                "SRTTTTTRS\n"
                "SRTTTTTRS\n"
                "SRTTTTTRS\n"
                "SRRRRRRRS\n"
                "SSSSSSSSS"
            )
            self.assertEqual(img_to_str(mask), expected)

    def test_wider_border(self):
        with Image(width=9, height=9) as mask:
            mask[4, 4] = 'white'
            highlightDifferences(mask, margin=1, edge_width=2)
            expected = (
                "SSSSSSSSS\n"
                "SRRRRRRRS\n"
                "SRRRRRRRS\n"
                "SRRTTTRRS\n"
                "SRRTTTRRS\n"
                "SRRTTTRRS\n"
                "SRRRRRRRS\n"
                "SRRRRRRRS\n"
                "SSSSSSSSS"
            )
            self.assertEqual(img_to_str(mask), expected)


if __name__ == '__main__':
    unittest.main()


def make_page(r, g, b, w, h):
    from pypdf._page import PageObject
    from pypdf.generic import DecodedStreamObject, NameObject
    page = PageObject.create_blank_page(width=w, height=h)
    content = DecodedStreamObject()
    content.set_data(f'q {r} {g} {b} rg 0 0 {w} {h} re f Q'.encode())
    page[NameObject('/Contents')] = content
    return page


def rasterize_page(page):
    writer = pypdf.PdfWriter()
    writer.add_page(page)
    buf = BytesIO()
    writer.write(buf)
    with Image(blob=buf.getvalue(), resolution=72) as img:
        img.background_color = 'white'
        img.alpha_channel = 'remove'
        img.format = 'png'
        return Image(blob=img.make_blob())


class TestPdfPrimitives(unittest.TestCase):

    def test_make_page_red(self):
        page = make_page(1, 0, 0, 50, 50)
        img = rasterize_page(page)
        self.assertEqual(img_to_str(img), ('R' * 50 + '\n') * 49 + 'R' * 50)

    def test_make_page_blue(self):
        page = make_page(0, 0, 1, 50, 50)
        img = rasterize_page(page)
        self.assertEqual(img_to_str(img), ('B' * 50 + '\n') * 49 + 'B' * 50)

    def test_sidebyside(self):
        red = make_page(1, 0, 0, 10, 10)
        blue = make_page(0, 0, 1, 10, 10)
        result = side_by_side(red, blue)
        img = rasterize_page(result)
        row = img_to_str(img)
        self.assertEqual(row, "\n".join(
            ["R" * 10 + "B" * 10]*10
        ))

    def test_overlay_image(self):
        white = make_page(1, 1, 1, 20, 10)
        with Image(width=20, height=10, background=Color('red')) as img:
            result = overlay_image(white, img)
        raster = rasterize_page(result)
        self.assertEqual(img_to_str(raster), "\n".join(
            ["R" * 20] * 10
        ))
