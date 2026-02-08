from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from mcp_server_redaction.recognizers.secrets import create_secrets_recognizers
from mcp_server_redaction.recognizers.financial import create_financial_recognizers
from mcp_server_redaction.recognizers.medical import create_medical_recognizers
from mcp_server_redaction.recognizers import build_registry


class TestSecretsRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_secrets_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_openai_api_key(self):
        analyzer = self._make_analyzer()
        text = "My key is sk-proj-abc123def456ghi789jkl012mno345pqr678"
        results = analyzer.analyze(text=text, language="en", entities=["API_KEY"])
        assert len(results) >= 1
        assert any(r.entity_type == "API_KEY" for r in results)

    def test_detect_github_token(self):
        analyzer = self._make_analyzer()
        text = "Use token ghp_1234567890abcdefghijklmnopqrstuv1234"
        results = analyzer.analyze(text=text, language="en", entities=["API_KEY"])
        assert len(results) >= 1

    def test_detect_aws_access_key(self):
        analyzer = self._make_analyzer()
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        results = analyzer.analyze(text=text, language="en", entities=["AWS_ACCESS_KEY"])
        assert len(results) >= 1

    def test_detect_connection_string_postgres(self):
        analyzer = self._make_analyzer()
        text = "DB: postgresql://user:password@host:5432/dbname"
        results = analyzer.analyze(text=text, language="en", entities=["CONNECTION_STRING"])
        assert len(results) >= 1

    def test_detect_connection_string_mongodb(self):
        analyzer = self._make_analyzer()
        text = "DB: mongodb://admin:secret@mongo.host:27017/mydb"
        results = analyzer.analyze(text=text, language="en", entities=["CONNECTION_STRING"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_text(self):
        analyzer = self._make_analyzer()
        text = "The sky is blue and the grass is green."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["API_KEY", "AWS_ACCESS_KEY", "CONNECTION_STRING"],
        )
        assert len(results) == 0


class TestFinancialRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_financial_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_visa_card(self):
        analyzer = self._make_analyzer()
        text = "Card: 4111111111111111"
        results = analyzer.analyze(text=text, language="en", entities=["CREDIT_CARD"])
        assert len(results) >= 1

    def test_detect_iban(self):
        analyzer = self._make_analyzer()
        text = "IBAN: GB29 NWBK 6016 1331 9268 19"
        results = analyzer.analyze(text=text, language="en", entities=["IBAN"])
        assert len(results) >= 1

    def test_detect_us_bank_routing(self):
        analyzer = self._make_analyzer()
        text = "Routing number: 021000021"
        results = analyzer.analyze(text=text, language="en", entities=["US_BANK_ROUTING"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_number(self):
        analyzer = self._make_analyzer()
        text = "I have 42 apples."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["CREDIT_CARD", "IBAN", "US_BANK_ROUTING"],
        )
        assert len(results) == 0


class TestMedicalRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_medical_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_icd10_code(self):
        analyzer = self._make_analyzer()
        text = "Diagnosis: J45.20 mild intermittent asthma"
        results = analyzer.analyze(text=text, language="en", entities=["ICD10_CODE"])
        assert len(results) >= 1

    def test_detect_medical_record_number(self):
        analyzer = self._make_analyzer()
        text = "MRN: 123-456-789"
        results = analyzer.analyze(text=text, language="en", entities=["MEDICAL_RECORD_NUMBER"])
        assert len(results) >= 1

    def test_detect_drug_name(self):
        analyzer = self._make_analyzer()
        text = "Patient is taking Metformin 500mg daily"
        results = analyzer.analyze(text=text, language="en", entities=["DRUG_NAME"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_text(self):
        analyzer = self._make_analyzer()
        text = "The weather is nice today."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["ICD10_CODE", "MEDICAL_RECORD_NUMBER", "DRUG_NAME"],
        )
        assert len(results) == 0


class TestBuildRegistry:
    def test_registry_has_custom_entities(self):
        registry = build_registry()
        supported = registry.get_supported_entities()
        for entity in ["API_KEY", "AWS_ACCESS_KEY", "CONNECTION_STRING",
                       "IBAN", "US_BANK_ROUTING",
                       "ICD10_CODE", "MEDICAL_RECORD_NUMBER", "DRUG_NAME"]:
            assert entity in supported, f"{entity} not in registry"

    def test_registry_has_default_entities(self):
        registry = build_registry()
        supported = registry.get_supported_entities()
        for entity in ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]:
            assert entity in supported, f"{entity} not in registry"
