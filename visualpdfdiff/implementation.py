#!/usr/bin/env python

import sys
from pathlib import Path
from itertools import zip_longest
import numpy as np
from consolemsg import step, warn, out, fail


def step(*args):
    pass


def tmpchanges(context):
    """Control uncleaned temporary files"""
    current = set(Path("/tmp").glob("*"))
    tmpchanges.initial = (
        tmpchanges.initial if hasattr(tmpchanges, "initial") else current
    )
    previous = tmpchanges.previous if hasattr(tmpchanges, "previous") else set()
    added = current - previous
    removed = previous - current
    tmpchanges.previous = current
    if not added and not removed:
        return
    if tmpchanges.initial == current:
        return
    warn(
        "{}: Temporary files left behind:\n{}",
        context,
        "\n".join(
            ["+ {}".format(tmp) for tmp in added]
            + ["- {}".format(tmp) for tmp in removed]
            + ["  {}".format(tmp) for tmp in current - tmpchanges.initial - added]
            + []
        ),
    )


def _fix_cropbox(page):
    if "/CropBox" in page:
        from pypdf.generic import NameObject

        page[NameObject("/CropBox")] = page.mediabox


def side_by_side(page_a, page_b):
    """Merge page_b to the right of page_a. Returns new page."""
    page_a.merge_translated_page(page_b, tx=page_a.mediabox.width, ty=0, expand=True)
    _fix_cropbox(page_a)
    return page_a


def overlay_image(page, image):
    """Merge a Wand image (as PDF) onto a pypdf page. Returns new page."""
    import pypdf
    from io import BytesIO

    image.format = "pdf"
    blob = image.make_blob()
    overlay_page = pypdf.PdfReader(BytesIO(blob)).pages[0]
    page.merge_translated_page(overlay_page, tx=0, ty=0, expand=True)
    _fix_cropbox(page)
    return page


def overlay_page(page, overlay_page, tx=0, ty=0):
    """Merge a pypdf page onto another at position (tx, ty). Returns new page."""
    page.merge_translated_page(overlay_page, tx=tx, ty=ty, expand=True)
    _fix_cropbox(page)
    return page


def img_to_array(img, channels="RGBA"):
    """Convert Wand image to numpy array of shape (h, w, len(channels))."""
    c = len(channels)
    return np.array(
        img.export_pixels(channel_map=channels),
        dtype=np.uint8,
    ).reshape(img.height, img.width, c)


def array_to_img(arr, channels="RGBA"):
    """Convert numpy uint8 array to Wand image."""
    from wand.image import Image

    h, w = arr.shape[:2]
    img = Image(width=w, height=h)
    img.import_pixels(0, 0, w, h, channels, "char", arr.astype(np.uint8).tobytes())
    return img


def dilate(mask, size, kernel="square"):
    """Binary dilation. mask is (h, w) uint8, size is kernel diameter.
    kernel: 'square' or 'circle'.
    """
    h, w = mask.shape
    result = np.zeros_like(mask, dtype=np.uint8)
    if kernel == "square":
        offsets = [
            (dy, dx)
            for dy in range(-(size // 2), size // 2 + 1)
            for dx in range(-(size // 2), size // 2 + 1)
        ]
    elif kernel == "circle":
        r = size // 2
        offsets = [
            (dy, dx)
            for dy in range(-r, r + 1)
            for dx in range(-r, r + 1)
            if dy**2 + dx**2 <= r**2
        ]

    for dy, dx in offsets:
        sy = slice(max(0, -dy), min(h, h - dy))
        sx = slice(max(0, -dx), min(w, w - dx))
        ry = slice(max(0, dy), min(h, h + dy))
        rx = slice(max(0, dx), min(w, w + dx))
        result[ry, rx] |= mask[sy, sx]

    return result


def mask_paint(target, mask, rgba):
    """Paint color onto target where mask is white."""
    from wand.color import Color

    dst = img_to_array(target, "RGBA")
    m = img_to_array(mask, "R")[:, :, 0]

    sel = m > 127

    c = Color(rgba)
    dst[sel, :] = np.array(
        [
            c.red * 255,
            c.green * 255,
            c.blue * 255,
            c.alpha * 255,
        ],
        dtype=np.uint8,
    )

    target.import_pixels(
        0, 0, target.width, target.height, "RGBA", "char", dst.tobytes()
    )


def build_diff_mask(img_a, img_b):
    """Compare two Wand images pixel-by-pixel. Returns (diff_image, ndiffs)."""
    from wand.color import Color

    a = img_to_array(img_a, "RGB")
    b = img_to_array(img_b, "RGB")

    h_a, w_a = a.shape[:2]
    h_b, w_b = b.shape[:2]
    w, h = max(w_a, w_b), max(h_a, h_b)

    canvas_a = np.full((h, w, 3), 255, dtype=np.uint8)
    canvas_b = np.full((h, w, 3), 255, dtype=np.uint8)
    canvas_a[:h_a, :w_a] = a
    canvas_b[:h_b, :w_b] = b

    mask = (np.abs(canvas_a.astype(int) - canvas_b.astype(int)).sum(axis=2) > 0).astype(
        np.uint8
    ) * 255

    ndiffs = mask.sum() / (255.0 * w * h)

    rgb = np.stack([mask, mask, mask], axis=2).astype(np.uint8)
    alpha = np.full((h, w, 1), 255, dtype=np.uint8)
    rgba = np.concatenate([rgb, alpha], axis=2)

    return array_to_img(rgba, "RGBA"), ndiffs


def buildDiffPdf(a, b, overlay, output, **params):
    import pypdf
    from io import BytesIO

    if overlay:
        overlayfile = BytesIO(overlay)

    step("Building diff pdf")

    def pages(reader):
        for i in range(len(reader.pages)):
            yield reader.pages[i]

    with a.open("rb") as afile, b.open("rb") as bfile, output.open("wb") as outputfile:
        areader = pypdf.PdfReader(afile)
        breader = pypdf.PdfReader(bfile)
        diffreader = pypdf.PdfReader(overlayfile)
        writer = pypdf.PdfWriter()

        # TODO: zip_longest instead of zip and manage Nones
        def blankWithDimensionsOf(otherPage):
            return pypdf._page.PageObject.create_blank_page(
                width=otherPage.mediabox.width,
                height=otherPage.mediabox.height,
            )

        for apage, bpage, diffpage in zip_longest(
            pages(areader), pages(breader), pages(diffreader)
        ):
            step(" Building page")
            missingA = not apage
            missingB = not bpage
            assert diffpage
            apage = apage or blankWithDimensionsOf(bpage)
            bpage = bpage or blankWithDimensionsOf(apage)
            if not missingB:
                apage = overlay_page(apage, diffpage)
            if not missingA:
                bpage = overlay_page(bpage, diffpage)
            apage = side_by_side(apage, bpage)
            writer.add_page(apage)
        step(" Writing pdf")
        writer.write(outputfile)


def centeredText(page, text, color="rgba(255,0,0,1)"):
    "Draws a centered text in the middle of a page"
    page.alpha_channel = "activate"
    page.opaque_paint("black", "rgba(240,255,255,.4)", channel="all_channels")
    from wand.drawing import Drawing

    with Drawing() as draw:
        draw.fill_color = f"{color}"
        draw.stroke_color = "grey"
        draw.stroke_width = 2
        draw.font_size = 40
        draw.font_weight = 700
        draw.gravity = "center"
        draw.text(0, 0, text)
        draw.stroke_color = "transparent"
        draw.text(0, 0, text)
        draw(page)


def highlightDifferences(diffimage, margin=2, edge_width=2):
    """Takes a B/W image with different pixels in white
    over a black background and returns a highlight
    semitransparent overlay with the corresponding pixels
    encircled in red.
    """
    from wand.image import Image
    from wand.color import Color

    total = margin + edge_width

    m = img_to_array(diffimage, "R")[:, :, 0]
    total_mask = dilate(m, total * 2 + 1)
    interior_mask = dilate(m, margin * 2 + 1)

    h, w = m.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:] = [255, 255, 0, 127]
    rgba[total_mask != 0] = [255, 0, 0, 255]
    rgba[interior_mask != 0] = [0, 0, 0, 0]

    result = array_to_img(rgba, "RGBA")
    diffimage.composite(result, 0, 0, "copy")


def rasterize(pdfimage):
    # pdf's just have the inked parts, so,
    # in order to simulate white paper
    # alpha channel is removed using white
    # as background color
    pdfimage.background_color = "white"
    pdfimage.alpha_channel = "remove"
    pdfimage.format = "png"
    return len(pdfimage.sequence)


def addMissingPageOverlay(overlay, page):
    from wand.image import Image

    with Image(
        background="black", height=page.height, width=page.width
    ) as missingOverlay:
        centeredText(missingOverlay, "MISSING\nPAGE")
        overlay.sequence.append(missingOverlay)


def visualEqual(a, b, outputdiff=None, **params):
    """Returns true if both pdf files a and b are
    pixel identical.

    If outputdiff is provided, a side by side
    pdf will be generated with the differences
    encircled in red.

    TODO: Pass as params things like metric,
    raster resolution,
    """

    from wand.display import display
    from wand.image import Image
    from wand.color import Color

    hasdifferences = False
    step("Comparing pdfs")
    step(" Loading pdfs")

    # An overlay for every page to mark pixel differences
    with Image() as overlay:
        overlay.alpha_channel = "set"

        with Image(filename=str(a)) as aimage, Image(filename=str(b)) as bimage:

            step(" Rasterizing pdfs")
            nPagesA = rasterize(aimage)
            nPagesB = rasterize(bimage)

            if nPagesA != nPagesB:
                hasdifferences = True
                if not outputdiff:
                    warn(
                        "Number of pages differ: {} has {} while {} has {}",
                        a,
                        nPagesA,
                        b,
                        nPagesB,
                    )
                    return False

            for i in range(min(nPagesA, nPagesB)):
                step(" Page {}", i)
                with aimage.sequence[i] as apage, bimage.sequence[i] as bpage:
                    diffpage, ndiffs = build_diff_mask(apage, bpage)
                    page_has_differences = ndiffs > 1e-14
                    with diffpage:
                        # Not generating outputdiff? be expeditive
                        if not outputdiff:
                            if page_has_differences:
                                return False
                            continue

                        if page_has_differences:
                            hasdifferences = True
                            warn(
                                "Page {} contains {:,.10f} different pixels", i, ndiffs
                            )
                            highlightDifferences(diffpage)
                        else:
                            centeredText(diffpage, "NO\nDIFFERENCES", "rgba(0,255,0,1)")

                        overlay.sequence.append(diffpage)

            for i in range(min(nPagesA, nPagesB), nPagesA):
                warn("Page {} only available in {}", i, a)
                addMissingPageOverlay(overlay, aimage.sequence[i])

            for i in range(min(nPagesA, nPagesB), nPagesB):
                warn("Page {} only available in {}", i, b)
                addMissingPageOverlay(overlay, bimage.sequence[i])

        if not outputdiff or not hasdifferences:
            return not hasdifferences

        overlay.format = "pdf"
        diff_overlay = overlay.make_blob()

        buildDiffPdf(a, b, diff_overlay, outputdiff)

    return False


def diff(a, b, diff):
    return visualEqual(Path(a), Path(b), diff and Path(diff))


def differences(expected, result, diffbase):
    """b2btest plugin interface: returns list of difference descriptions."""
    result_pdf = Path(diffbase + ".pdf")
    are_equal = visualEqual(
        Path(expected),
        Path(result),
        result_pdf,
    )
    if are_equal:
        return []
    return [
        f"Visual differences found between {expected} and {result}. "
        f"See diff output at {result_pdf}"
    ]


differences.extensions = [".pdf"]
