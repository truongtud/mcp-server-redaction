import pytest
from presidio_analyzer import AnalyzerEngine

from mcp_server_redaction.recognizers import build_registry


class TestGLiNERRecognizer:
    @pytest.fixture(autouse=True)
    def setup(self):
        registry = build_registry()
        self.analyzer = AnalyzerEngine(registry=registry)

    def test_detect_person_multilingual(self):
        """GLiNER should catch names that spaCy might miss."""
        text = "Kontaktieren Sie Herrn Müller unter hans.mueller@firma.de"
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        assert "EMAIL_ADDRESS" in entity_types  # regex catches this
        assert "PERSON" in entity_types  # GLiNER should catch "Herrn Müller"

    def test_detect_organization(self):
        text = "I work at Deutsche Telekom AG in Bonn."
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        assert "ORGANIZATION" in entity_types or "PERSON" in entity_types

    def test_detect_address(self):
        text = "Ship to 742 Evergreen Terrace, Springfield, IL 62704"
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        # GLiNER should find address components
        assert len(results) > 0

    def test_gliner_entities_have_scores(self):
        text = "Contact John Smith at john@example.com"
        results = self.analyzer.analyze(text, language="en")
        for r in results:
            assert 0.0 < r.score <= 1.0
