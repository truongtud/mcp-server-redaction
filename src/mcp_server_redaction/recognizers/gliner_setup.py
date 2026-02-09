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
    "passport number": "PASSPORT",
    "email": "EMAIL_ADDRESS",
    "credit card number": "CREDIT_CARD",
    "social security number": "US_SSN",
    "date of birth": "DATE_TIME",
    "mobile phone number": "PHONE_NUMBER",
    "bank account number": "US_BANK_NUMBER",
    "medication": "DRUG_NAME",
    "driver's license number": "US_DRIVER_LICENSE",
    "tax identification number": "TAX_ID",
    "medical condition": "MEDICAL_CONDITION",
    "identity card number": "NATIONAL_ID",
    "national id number": "NATIONAL_ID",
    "ip address": "IP_ADDRESS",
    "iban": "IBAN",
    "username": "USERNAME",
    "health insurance number": "INSURANCE_ID",
    "insurance number": "INSURANCE_ID",
    "registration number": "REGISTRATION_NUMBER",
    "postal code": "POSTAL_CODE",
    "license plate number": "LICENSE_PLATE",
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
