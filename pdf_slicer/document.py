"""PDF 文档访问模块。

封装 PyMuPDF 的常用读取与切片能力，并统一对外暴露 1-based 页码。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from .errors import (
    DamagedPdfError,
    EmptyPdfError,
    EncryptedPdfError,
    InputPdfNotFoundError,
    UnsupportedInputError,
)


class PdfDocument:
    """Thin wrapper around PyMuPDF with 1-based public page numbers."""

    def __init__(self, path: Path, document: pymupdf.Document):
        self.path = Path(path)
        self._document = document

    @classmethod
    def open(cls, path: str | Path) -> "PdfDocument":
        """打开并预检 PDF。

        会在这里完成文件存在性、加密、空文档和文本层支持性检查。
        """
        path_obj = Path(path)
        if not path_obj.exists():
            raise InputPdfNotFoundError(f"Input PDF not found: {path_obj}")

        try:
            document = pymupdf.open(path_obj)
        except Exception as exc:  # pragma: no cover
            raise DamagedPdfError(f"Failed to open PDF: {path_obj}") from exc

        if document.needs_pass or document.is_encrypted:
            document.close()
            raise EncryptedPdfError("Encrypted PDF is not supported. Please decrypt it first.")

        if document.page_count == 0:
            document.close()
            raise EmptyPdfError("PDF contains zero pages.")

        wrapper = cls(path_obj, document)
        if not wrapper.has_text_layer():
            wrapper.close()
            raise UnsupportedInputError(
                "Current version supports only digital PDFs with extractable text layers."
            )
        return wrapper

    @property
    def total_pages(self) -> int:
        return self._document.page_count

    def close(self) -> None:
        self._document.close()

    def has_text_layer(self) -> bool:
        """判断文档是否具备可提取文本层。"""
        # Phase 1 明确只支持可提取文本的数字 PDF；任意一页能抽到文本即可继续。
        for page_number in range(1, self.total_pages + 1):
            if self.page_text(page_number).strip():
                return True
        return False

    def page_text(self, page_number: int) -> str:
        return self.get_page(page_number).get_text("text", sort=True)

    def get_page(self, page_number: int) -> pymupdf.Page:
        self._validate_page_number(page_number)
        return self._document.load_page(page_number - 1)

    def get_toc(self, simple: bool = True) -> list[list[Any]]:
        return self._document.get_toc(simple=simple)

    def get_text_blocks(self, page_number: int) -> list[tuple[Any, ...]]:
        return self.get_page(page_number).get_text("blocks", sort=True)

    def get_text_dict(self, page_number: int) -> dict[str, Any]:
        return self.get_page(page_number).get_text("dict", sort=True)

    def get_image_blocks(self, page_number: int) -> list[dict[str, Any]]:
        page_dict = self.get_text_dict(page_number)
        return [block for block in page_dict.get("blocks", []) if block.get("type") == 1]

    def find_tables(self, page_number: int) -> Any:
        return self.get_page(page_number).find_tables()

    def slice_pdf(self, start_page: int, end_page: int, output_path: str | Path) -> Path:
        """按 1-based 页码区间导出子 PDF。"""
        # 对外一律使用 1-based 页码，这里是唯一落到 PyMuPDF 0-based 区间复制的地方。
        self._validate_page_number(start_page)
        self._validate_page_number(end_page)
        if end_page < start_page:
            raise ValueError("end_page must be greater than or equal to start_page")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sliced_document = pymupdf.open()
        sliced_document.insert_pdf(
            self._document,
            from_page=start_page - 1,
            to_page=end_page - 1,
        )
        sliced_document.save(output_path)
        sliced_document.close()
        return output_path

    def _validate_page_number(self, page_number: int) -> None:
        if page_number < 1 or page_number > self.total_pages:
            raise ValueError(f"Page number out of range: {page_number}")
