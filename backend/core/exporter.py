"""EPUB and PDF exporters for translated novels."""

from __future__ import annotations

import html
import io
import mimetypes
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fpdf import FPDF

_WINDOWS_FONTS = [
    (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
    ),
    (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ),
    (
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
    ),
]

_LINUX_FONTS = [
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
]


def format_chapter_heading(chapter: dict[str, Any]) -> str:
    """Return a clean chapter heading without duplicating 'Bab N'."""
    heading = (chapter.get("title_translated") or chapter.get("title") or "").strip()
    number = chapter["chapter_number"]
    number_label = int(number) if float(number) == int(number) else number
    if heading and re.match(r"^\s*(bab|chapter|第)\s*\d", heading, re.IGNORECASE):
        return heading
    return f"Bab {number_label}" + (f": {heading}" if heading else "")


def _display_title(novel: dict[str, Any]) -> str:
    return (novel.get("title_translated") or novel.get("title") or "Novel").strip()


def _display_synopsis(novel: dict[str, Any]) -> str:
    return (novel.get("synopsis_translated") or novel.get("synopsis") or "").strip()


def _resolve_cover(novel: dict[str, Any]) -> tuple[Path, bytes, str, str] | None:
    raw_path = (novel.get("cover_path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    ext = path.suffix.lower().lstrip(".") or "png"
    media_type, _ = mimetypes.guess_type(path.name)
    if not media_type:
        media_type = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
    return path, path.read_bytes(), media_type, ext


def _paragraphs_to_xhtml(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\r?\n+", text or "") if p.strip()]
    if not paras:
        return "<p></p>"
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in paras)


def build_epub(novel: dict[str, Any], chapters: list[dict[str, Any]]) -> bytes:
    """Package translated chapters (and optional cover) into an EPUB 3 archive."""
    novel_uid = novel.get("id", 0)
    book_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'translatale-{novel_uid}')}"
    title = _display_title(novel)
    author = (novel.get("author") or "Unknown").strip()
    lang = (novel.get("target_lang") or "id").strip()
    synopsis = _display_synopsis(novel)
    cover = _resolve_cover(novel)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # EPUB spec requires mimetype to be the first entry and stored uncompressed.
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            "  <rootfiles>\n"
            '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n"
            "</container>\n",
            compress_type=zipfile.ZIP_DEFLATED,
        )

        css = (
            "body { font-family: Georgia, serif; line-height: 1.7; margin: 1.5em; color: #1e293b; }\n"
            "h1, h2 { font-family: sans-serif; line-height: 1.3; margin-bottom: 0.8em; }\n"
            "p { margin: 0 0 0.9em 0; text-indent: 0; }\n"
            ".meta { color: #64748b; font-size: 0.95em; margin-bottom: 1.5em; }\n"
            ".cover-wrap { text-align: center; margin: 0; }\n"
            ".cover-wrap img { max-width: 100%; max-height: 95vh; }\n"
        )
        zf.writestr("OEBPS/style.css", css, compress_type=zipfile.ZIP_DEFLATED)

        manifest_items: list[str] = [
            '<item id="style" href="style.css" media-type="text/css"/>',
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        ]
        spine_items: list[str] = []
        nav_entries: list[tuple[str, str]] = []
        extra_meta = ""

        if cover is not None:
            _, cover_bytes, cover_mime, cover_ext = cover
            cover_href = f"cover.{cover_ext}"
            zf.writestr(f"OEBPS/{cover_href}", cover_bytes, compress_type=zipfile.ZIP_DEFLATED)
            manifest_items.append(
                f'<item id="cover-image" href="{cover_href}" media-type="{cover_mime}" properties="cover-image"/>'
            )
            manifest_items.append(
                '<item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>'
            )
            spine_items.append('<itemref idref="cover-page"/>')
            extra_meta = '<meta name="cover" content="cover-image"/>'
            cover_xhtml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE html>\n'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{html.escape(lang)}">\n'
                f'<head><title>{html.escape(title)}</title>'
                '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
                f'<body><div class="cover-wrap"><img src="{cover_href}" alt="{html.escape(title)}"/></div></body>\n'
                "</html>\n"
            )
            zf.writestr("OEBPS/cover.xhtml", cover_xhtml, compress_type=zipfile.ZIP_DEFLATED)

        synopsis_html = _paragraphs_to_xhtml(synopsis) if synopsis else ""
        title_xhtml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{html.escape(lang)}">\n'
            f'<head><title>{html.escape(title)}</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            "<body>\n"
            f"<h1>{html.escape(title)}</h1>\n"
            f'<p class="meta">{html.escape(author)}</p>\n'
            f"{synopsis_html}\n"
            "</body>\n</html>\n"
        )
        zf.writestr("OEBPS/title.xhtml", title_xhtml, compress_type=zipfile.ZIP_DEFLATED)
        manifest_items.append(
            '<item id="title-page" href="title.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append('<itemref idref="title-page"/>')
        nav_entries.append(("title.xhtml", title))

        for idx, chapter in enumerate(chapters, start=1):
            heading = format_chapter_heading(chapter)
            href = f"chap_{idx:04d}.xhtml"
            item_id = f"chap_{idx:04d}"
            body_html = _paragraphs_to_xhtml(chapter.get("translated_content") or "")
            chap_xhtml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE html>\n'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{html.escape(lang)}">\n'
                f'<head><title>{html.escape(heading)}</title>'
                '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
                f"<body>\n<h2>{html.escape(heading)}</h2>\n{body_html}\n</body>\n</html>\n"
            )
            zf.writestr(f"OEBPS/{href}", chap_xhtml, compress_type=zipfile.ZIP_DEFLATED)
            manifest_items.append(
                f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
            )
            spine_items.append(f'<itemref idref="{item_id}"/>')
            nav_entries.append((href, heading))

        nav_lis = "\n".join(
            f'      <li><a href="{href}">{html.escape(label)}</a></li>'
            for href, label in nav_entries
        )
        nav_xhtml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{html.escape(lang)}">\n'
            f"<head><title>{html.escape(title)}</title></head>\n"
            "<body>\n"
            '  <nav epub:type="toc" id="toc">\n'
            f"    <h1>{html.escape(title)}</h1>\n"
            f"    <ol>\n{nav_lis}\n    </ol>\n"
            "  </nav>\n"
            "</body>\n</html>\n"
        )
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)

        ncx_points = "\n".join(
            f'    <navPoint id="navPoint-{i}" playOrder="{i}">'
            f"<navLabel><text>{html.escape(label)}</text></navLabel>"
            f'<content src="{href}"/></navPoint>'
            for i, (href, label) in enumerate(nav_entries, start=1)
        )
        toc_ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            "  <head>\n"
            f'    <meta name="dtb:uid" content="{html.escape(book_id)}"/>\n'
            "  </head>\n"
            f"  <docTitle><text>{html.escape(title)}</text></docTitle>\n"
            f"  <navMap>\n{ncx_points}\n  </navMap>\n"
            "</ncx>\n"
        )
        zf.writestr("OEBPS/toc.ncx", toc_ncx, compress_type=zipfile.ZIP_DEFLATED)

        manifest_xml = "\n    ".join(manifest_items)
        spine_xml = "\n    ".join(spine_items)
        content_opf = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="bookid">{html.escape(book_id)}</dc:identifier>\n'
            f"    <dc:title>{html.escape(title)}</dc:title>\n"
            f"    <dc:creator>{html.escape(author)}</dc:creator>\n"
            f"    <dc:language>{html.escape(lang)}</dc:language>\n"
            f"    {extra_meta}\n"
            "  </metadata>\n"
            f"  <manifest>\n    {manifest_xml}\n  </manifest>\n"
            f'  <spine toc="ncx">\n    {spine_xml}\n  </spine>\n'
            "</package>\n"
        )
        zf.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)

    return buf.getvalue()


class _NovelPDF(FPDF):
    def __init__(self, font_family: str) -> None:
        super().__init__()
        self._font_family = font_family

    def footer(self) -> None:
        if self.page_no() <= 1:
            return
        self.set_y(-14)
        self.set_font(self._font_family, size=9)
        self.set_text_color(120, 130, 145)
        self.cell(0, 8, str(self.page_no()), align="C")


def _configure_pdf_font(pdf: FPDF) -> tuple[str, bool]:
    for regular, bold in [*_WINDOWS_FONTS, *_LINUX_FONTS]:
        if regular.is_file():
            pdf.add_font("BodyFont", style="", fname=str(regular))
            if bold.is_file():
                pdf.add_font("BodyFont", style="B", fname=str(bold))
            else:
                pdf.add_font("BodyFont", style="B", fname=str(regular))
            return "BodyFont", True
    return "helvetica", False


def _clean_pdf_text(text: str, unicode_ready: bool) -> str:
    if unicode_ready:
        return text
    return text.encode("latin-1", "replace").decode("latin-1")


def build_pdf(novel: dict[str, Any], chapters: list[dict[str, Any]]) -> bytes:
    """Render translated chapters (and optional cover) into a PDF document."""
    pdf = _NovelPDF("helvetica")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 20, 20)
    font_family, unicode_ready = _configure_pdf_font(pdf)
    pdf._font_family = font_family

    title = _display_title(novel)
    author = (novel.get("author") or "").strip()
    synopsis = _display_synopsis(novel)
    pdf.set_title(_clean_pdf_text(title, unicode_ready))
    if author:
        pdf.set_author(_clean_pdf_text(author, unicode_ready))

    cover = _resolve_cover(novel)
    if cover is not None:
        cover_path, _, _, _ = cover
        pdf.add_page()
        max_w = pdf.w - 40
        max_h = pdf.h - 40
        pdf.image(str(cover_path), x=20, y=20, w=max_w, h=max_h, keep_aspect_ratio=True)

    # Title & synopsis page
    pdf.add_page()
    pdf.set_text_color(20, 24, 35)
    pdf.set_font(font_family, style="B", size=20)
    pdf.multi_cell(0, 10, _clean_pdf_text(title, unicode_ready))
    if author:
        pdf.ln(2)
        pdf.set_font(font_family, size=12)
        pdf.set_text_color(90, 100, 115)
        pdf.multi_cell(0, 7, _clean_pdf_text(author, unicode_ready))
    if synopsis:
        pdf.ln(8)
        pdf.set_text_color(40, 48, 60)
        pdf.set_font(font_family, size=11)
        for para in re.split(r"\r?\n+", synopsis):
            cleaned = para.strip()
            if cleaned:
                pdf.multi_cell(0, 6.5, _clean_pdf_text(cleaned, unicode_ready))
                pdf.ln(2.5)

    # Chapters
    for chapter in chapters:
        pdf.add_page()
        heading = format_chapter_heading(chapter)
        pdf.set_text_color(15, 23, 42)
        pdf.set_font(font_family, style="B", size=14)
        pdf.multi_cell(0, 8, _clean_pdf_text(heading, unicode_ready))
        pdf.ln(4)

        pdf.set_text_color(30, 41, 59)
        pdf.set_font(font_family, size=11)
        body = chapter.get("translated_content") or ""
        for para in re.split(r"\r?\n+", body):
            cleaned = para.strip()
            if cleaned:
                pdf.multi_cell(0, 6.5, _clean_pdf_text(cleaned, unicode_ready))
                pdf.ln(2.5)

    return bytes(pdf.output())
