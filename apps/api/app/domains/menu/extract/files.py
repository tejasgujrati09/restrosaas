"""Untrusted-file handling: what a file really is, how many pages it has, and turning pages into
provider input. CPU-bound and synchronous; callers run it in a thread.

The type is decided from the file's leading bytes, never from its name or the browser's
content type. A PDF page with a real text layer is sent as text (cheaper, exact); a scanned page
is rendered to an image. Images are straightened by their EXIF orientation and only shrunk when
their longest side is over the configured limit."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.domains.menu.extract.provider import PageInput

Kind = Literal["pdf", "jpeg", "png"]
MIME: dict[Kind, str] = {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png"}
_MAX_PIXELS = 60_000_000


class FileProblem(Exception):
    """A message safe to show the owner."""


@dataclass(frozen=True)
class FileInfo:
    kind: Kind
    pages: int


def sniff(data: bytes) -> Kind | None:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def _open_pdf(name: str, data: bytes) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise FileProblem(f"{name} is damaged, password-protected or not a real PDF.") from exc


def _open_image(name: str, data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > _MAX_PIXELS:
            raise FileProblem(f"{name} is too large to read. Use a smaller photo.")
        image.load()
        return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise FileProblem(f"{name} could not be read as an image.") from exc


def inspect(name: str, data: bytes) -> FileInfo:
    kind = sniff(data)
    if kind is None:
        raise FileProblem(f"{name} is not supported. Use a PDF, JPG or PNG.")
    if kind == "pdf":
        pdf = _open_pdf(name, data)
        try:
            pages = len(pdf)
        finally:
            pdf.close()
        if pages == 0:
            raise FileProblem(f"{name} has no pages.")
        return FileInfo(kind, pages)
    _open_image(name, data).close()
    return FileInfo(kind, 1)


def _encode(image: Image.Image) -> tuple[bytes, str]:
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


def _fit(image: Image.Image) -> Image.Image:
    limit = settings.menu_extraction_max_image_px
    longest = max(image.size)
    if longest <= limit:
        return image
    ratio = limit / longest
    return image.resize(
        (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
        Image.Resampling.LANCZOS,
    )


def _image_page(number: int, label: str, name: str, data: bytes, kind: Kind) -> PageInput:
    image = _open_image(name, data)
    untouched = image.getexif().get(0x0112, 1) == 1 and max(image.size) <= (
        settings.menu_extraction_max_image_px
    )
    if kind == "jpeg" and untouched:
        return PageInput(number, label, image=data, image_mime="image/jpeg")
    encoded, mime = _encode(_fit(ImageOps.exif_transpose(image)))
    return PageInput(number, label, image=encoded, image_mime=mime)


def _pdf_page(number: int, label: str, pdf: pdfium.PdfDocument, index: int) -> PageInput:
    page = pdf[index]
    try:
        text_page = page.get_textpage()
        text = (text_page.get_text_range() or "").strip()
        text_page.close()
        if len(text) >= settings.menu_extraction_min_text_chars:
            return PageInput(number, label, text=text)
        width, height = page.get_size()
        scale = min(3.0, settings.menu_extraction_max_image_px / max(width, height, 1.0))
        bitmap = page.render(scale=scale, rotation=0, may_draw_forms=False)
        encoded, mime = _encode(bitmap.to_pil())
        return PageInput(number, label, image=encoded, image_mime=mime)
    finally:
        page.close()


def load_pages(files: list[tuple[str, bytes]]) -> list[PageInput]:
    """All pages of all files, in upload order then page order, numbered from 1."""
    pages: list[PageInput] = []
    for name, data in files:
        kind = sniff(data)
        if kind is None:
            raise FileProblem(f"{name} is not supported. Use a PDF, JPG or PNG.")
        if kind == "pdf":
            pdf = _open_pdf(name, data)
            try:
                for index in range(len(pdf)):
                    number = len(pages) + 1
                    pages.append(_pdf_page(number, f"{name}, page {index + 1}", pdf, index))
            finally:
                pdf.close()
        else:
            number = len(pages) + 1
            pages.append(_image_page(number, name, name, data, kind))
    return pages


__all__ = ["MIME", "FileInfo", "FileProblem", "inspect", "load_pages", "sniff"]
