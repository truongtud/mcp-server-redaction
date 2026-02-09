from presidio_analyzer import Pattern, PatternRecognizer


def create_financial_recognizers() -> list[PatternRecognizer]:
    # Presidio has a built-in CREDIT_CARD recognizer, but we add IBAN and routing.
    iban_recognizer = PatternRecognizer(
        supported_entity="IBAN",
        name="IbanRecognizer",
        patterns=[
            Pattern(
                "iban",
                r"\b[A-Z]{2}\d{2}\s?[\dA-Z]{4}\s?(?:[\dA-Z]{4}\s?){2,7}[\dA-Z]{1,4}\b",
                0.8,
            ),
        ],
        context=["iban", "account", "bank", "transfer"],
    )

    routing_recognizer = PatternRecognizer(
        supported_entity="US_BANK_ROUTING",
        name="UsBankRoutingRecognizer",
        patterns=[
            Pattern("us_routing", r"\b\d{9}\b", 0.3),
        ],
        context=["routing", "aba", "bank", "transit"],
    )

    swift_recognizer = PatternRecognizer(
        supported_entity="SWIFT_CODE",
        name="SwiftCodeRecognizer",
        patterns=[
            Pattern("swift_11", r"\b[A-Z]{6}[A-Z0-9]{2}[A-Z0-9]{3}\b", 0.7),
            Pattern("swift_8", r"\b[A-Z]{6}[A-Z0-9]{2}\b", 0.5),
        ],
        context=["swift", "bic", "bank", "transfer", "wire"],
    )

    postal_code_recognizer = PatternRecognizer(
        supported_entity="POSTAL_CODE",
        name="PostalCodeRecognizer",
        patterns=[
            Pattern("us_zip", r"\b\d{5}(?:-\d{4})?\b", 0.3),
            Pattern("uk_postcode", r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", 0.5),
            Pattern("de_plz", r"\b\d{5}\b", 0.2),
        ],
        context=["zip", "postal", "postcode", "plz", "address", "city"],
    )

    return [iban_recognizer, routing_recognizer, swift_recognizer, postal_code_recognizer]
