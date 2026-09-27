from dataclasses import dataclass

import pymupdf


@dataclass
class Page:
    number: int
    text: str


def extract_pdf(data: bytes, max_pages: int) -> tuple[list[Page], int]:
    if not data.lstrip().startswith(b'%PDF-'):
        raise ValueError('The file is not a valid PDF.')
    try:
        with pymupdf.open(stream=data, filetype='pdf') as document:
            if document.needs_pass:
                raise ValueError('Password-protected PDFs are not supported.')
            if len(document) > max_pages:
                raise ValueError(f'PDF exceeds the {max_pages}-page limit.')
            pages = [Page(i + 1, page.get_text('text', sort=True).strip())
                     for i, page in enumerate(document)]
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ValueError('Unable to read this PDF.') from exc
    empty = sum(not page.text for page in pages)
    if not any(page.text for page in pages):
        raise ValueError('No extractable text. This PDF needs OCR, planned for Milestone 2.')
    return pages, empty
