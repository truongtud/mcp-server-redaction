from presidio_analyzer import RecognizerRegistry

from .financial import create_financial_recognizers
from .gliner_setup import create_gliner_recognizer
from .medical import create_medical_recognizers
from .secrets import create_secrets_recognizers


def build_registry() -> RecognizerRegistry:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for recognizer in create_secrets_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_financial_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_medical_recognizers():
        registry.add_recognizer(recognizer)

    gliner = create_gliner_recognizer()
    if gliner is not None:
        registry.add_recognizer(gliner)

    return registry
