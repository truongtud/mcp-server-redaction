from .base import FileHandler
from .docx_handler import DocxHandler
from .pdf import PdfHandler
from .plain_text import PlainTextHandler
from .xlsx import XlsxHandler

_HANDLER_MAP: dict[str, type[FileHandler]] = {
    ".txt": PlainTextHandler,
    ".csv": PlainTextHandler,
    ".log": PlainTextHandler,
    ".md": PlainTextHandler,
    ".docx": DocxHandler,
    ".xlsx": XlsxHandler,
    ".pdf": PdfHandler,
}


def get_handler(extension: str) -> FileHandler:
    """Return a handler instance for the given file extension.

    Raises ValueError if the extension is not supported.
    """
    ext = extension.lower()
    handler_cls = _HANDLER_MAP.get(ext)
    if handler_cls is None:
        supported = ", ".join(sorted(_HANDLER_MAP.keys()))
        raise ValueError(
            f"Unsupported file extension: '{ext}'. Supported: {supported}"
        )
    return handler_cls()
