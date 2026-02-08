import os
import shutil
import subprocess
import tempfile

from ..engine import RedactionEngine
from .base import FileHandler
from .docx_handler import DocxHandler


class DocHandler(FileHandler):
    """Handles legacy .doc files by converting to .docx via LibreOffice."""

    def __init__(self):
        self._docx_handler = DocxHandler()

    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        self._check_libreoffice()
        docx_path = self._convert_to_docx(input_path)
        try:
            return self._docx_handler.redact(
                engine, docx_path, output_path,
                entity_types=entity_types,
                use_placeholders=use_placeholders,
            )
        finally:
            os.unlink(docx_path)

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        # Input will be a .docx (from a previous redact), delegate directly
        return self._docx_handler.unredact(input_path, output_path, mappings)

    @staticmethod
    def _check_libreoffice() -> None:
        if shutil.which("libreoffice") is None:
            raise RuntimeError(
                "LibreOffice is required for .doc file support. "
                "Install it: https://www.libreoffice.org/download/"
            )

    @staticmethod
    def _convert_to_docx(doc_path: str) -> str:
        """Convert a .doc file to .docx using LibreOffice. Returns path to the .docx."""
        tmpdir = tempfile.mkdtemp()
        subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "docx",
                "--outdir", tmpdir, doc_path,
            ],
            check=True,
            capture_output=True,
        )
        base = os.path.splitext(os.path.basename(doc_path))[0]
        return os.path.join(tmpdir, f"{base}.docx")
