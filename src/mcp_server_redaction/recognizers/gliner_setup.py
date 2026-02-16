import logging

from presidio_analyzer import EntityRecognizer

logger = logging.getLogger(__name__)

# Mapping from GLiNER's entity labels to Presidio entity types.
# GLiNER model: urchade/gliner_multi_pii-v1
GLINER_ENTITY_MAPPING = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "phone number": "PHONE_NUMBER",
    "address": "LOCATION",
    "email": "EMAIL_ADDRESS",
    "date of birth": "DATE_TIME",
    "mobile phone number": "PHONE_NUMBER",
    "medication": "DRUG_NAME",
    "medical condition": "MEDICAL_CONDITION",
    "username": "USERNAME",
}


def create_gliner_recognizer() -> EntityRecognizer | None:
    """Create a GLiNER-based recognizer. Returns None if GLiNER is unavailable."""
    try:
        from presidio_analyzer.predefined_recognizers import GLiNERRecognizer
    except ImportError:
        logger.warning(
            "GLiNER not available. Install with: pip install 'presidio-analyzer[gliner]'"
        )
        return None

    try:
        recognizer = GLiNERRecognizer(
            model_name="urchade/gliner_multi_pii-v1",
            entity_mapping=GLINER_ENTITY_MAPPING,
            flat_ner=False,
            multi_label=True,
            map_location="cpu",
        )
        logger.info("GLiNER recognizer loaded successfully")
        return recognizer
    except Exception:
        logger.exception("Failed to load GLiNER model")
        return None
