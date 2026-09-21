"""Keep full source picture coordinates independent of its display size."""
import io
from PIL import Image

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def set_picture_display_size(picture, width, height):
    """Resize the visible shape while preserving its complete source pixels."""
    for name in ("curSz", "sz"):
        picture.find(HP + name).attrib.update({"width": str(round(width)), "height": str(round(height))})
    original = picture.find(HP + "orgSz")
    picture.find(HP + "renderingInfo/" + HC + "scaMatrix").attrib.update(
        {"e1": str(round(width) / int(original.get("width"))),
         "e5": str(round(height) / int(original.get("height")))})


def restore_picture_coordinates(section, payloads, hrefs):
    """Native PDF figures already contain exactly the retained source crop.

    Their image coordinate space is the embedded bitmap at 96 DPI (75 HWPUNIT
    per pixel). A smaller display rectangle must scale it, not crop it again.
    """
    for picture in section.iter(HP + "pic"):
        image = picture.find(HC + "img")
        href = hrefs.get(image.get("binaryItemIDRef")) if image is not None else None
        if href not in payloads:
            raise ValueError("Native picture has no embedded source bitmap")
        with Image.open(io.BytesIO(payloads[href])) as bitmap:
            original_width, original_height = bitmap.width * 75, bitmap.height * 75
        display = picture.find(HP + "sz")
        width, height = int(display.get("width")), int(display.get("height"))
        picture.find(HP + "orgSz").attrib.update({"width": str(original_width), "height": str(original_height)})
        picture.find(HP + "imgDim").attrib.update({"dimwidth": str(original_width), "dimheight": str(original_height)})
        picture.find(HP + "imgClip").attrib.update({"left": "0", "top": "0", "right": str(original_width), "bottom": str(original_height)})
        for index, (x, y) in enumerate(((0, 0), (original_width, 0), (original_width, original_height), (0, original_height))):
            picture.find(HP + "imgRect/" + HC + f"pt{index}").attrib.update({"x": str(x), "y": str(y)})
        set_picture_display_size(picture, width, height)


def has_complete_picture_crop(picture, payload):
    """Check the native crop against actual embedded pixels, not writer stats."""
    try:
        with Image.open(io.BytesIO(payload)) as bitmap:
            expected = (bitmap.width * 75, bitmap.height * 75)
        clip, dim = (picture.find(HP + name) for name in ("imgClip", "imgDim"))
        return (tuple(int(clip.get(k)) for k in ("left", "top", "right", "bottom")) == (0, 0, *expected)
                and tuple(int(dim.get(k)) for k in ("dimwidth", "dimheight")) == expected)
    except (AttributeError, TypeError, ValueError, OSError):
        return False


def restore_single_picture_paragraph(paragraph, layout, page_width, column_width, para_style):
    """Use the source inset and size for a flowing, image-only paragraph."""
    pictures = paragraph.findall(HP + "run/" + HP + "pic")
    bounds = layout.get("source_image_bounds") or []
    if (len(pictures) != 1 or len(bounds) != 1
        or layout.get("column_left_pt") is None
        or not layout.get("source_page_width_pt")
        or any((t.text or "").strip() for t in paragraph.findall(HP + "run/" + HP + "t"))):
        return False
    x0, y0, x1, y1 = map(float, bounds[0])
    scale = page_width / float(layout["source_page_width_pt"])
    left = round((x0 - float(layout["column_left_pt"])) * scale)
    width, height = round((x1 - x0) * scale), round((y1 - y0) * scale)
    if left < 0 or min(width, height) <= 0 or left + width > column_width + 1:
        return False
    paragraph.set("paraPrIDRef", para_style(paragraph.get("paraPrIDRef"), "LEFT", 1000, 1000))
    picture = pictures[0]
    set_picture_display_size(picture, width, height)
    # A paragraph anchor is the native representation of an inset standalone
    # figure. TOP_AND_BOTTOM reserves its band in the document flow; the
    # picture moves with this paragraph when preceding text is edited.
    picture.set("textWrap", "TOP_AND_BOTTOM")
    picture.find(HP + "pos").attrib.update({
        "treatAsChar": "0", "affectLSpacing": "1", "flowWithText": "1",
        "allowOverlap": "0", "vertRelTo": "PARA", "horzRelTo": "COLUMN",
        "vertAlign": "TOP", "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": str(left),
    })
    margin = picture.find(HP + "outMargin")
    if margin is not None:
        for name in ("left", "right", "top", "bottom"):
            margin.set(name, "0")
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    _set_paragraph_element_lineseg(paragraph, height + 300, width=round(column_width), spacing_ratio=0.0)
    paragraph.set("nativeParagraphWidth", str(round(column_width)))
    return True
