from ..engine import RedactionEngine
from .base import FileHandler


class PlainTextHandler(FileHandler):
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        with open(input_path) as f:
            content = f.read()

        result = engine.redact(content, entity_types=entity_types)

        with open(output_path, "w") as f:
            f.write(result["redacted_text"])

        return {
            "session_id": result["session_id"],
            "entities_found": result["entities_found"],
        }

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        with open(input_path) as f:
            content = f.read()

        entities_restored = 0
        for placeholder, original in mappings.items():
            if placeholder in content:
                content = content.replace(placeholder, original)
                entities_restored += 1

        with open(output_path, "w") as f:
            f.write(content)

        return {"entities_restored": entities_restored}
