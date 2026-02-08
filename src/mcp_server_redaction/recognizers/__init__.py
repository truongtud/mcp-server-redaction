from presidio_analyzer import RecognizerRegistry

from .secrets import create_secrets_recognizers
from .financial import create_financial_recognizers
from .medical import create_medical_recognizers


def build_registry() -> RecognizerRegistry:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for recognizer in create_secrets_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_financial_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_medical_recognizers():
        registry.add_recognizer(recognizer)

    return registry
