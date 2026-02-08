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

    return [iban_recognizer, routing_recognizer]
