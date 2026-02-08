from abc import ABC, abstractmethod

from ..engine import RedactionEngine


class FileHandler(ABC):
    @abstractmethod
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        """Redact sensitive data in the file. Write result to output_path.

        Returns dict with keys: session_id (str or None), entities_found (int).
        session_id is None when use_placeholders=False (irreversible redaction).
        """

    @abstractmethod
    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        """Replace placeholders in the file using mappings.

        Returns dict with keys: entities_restored (int).
        """
