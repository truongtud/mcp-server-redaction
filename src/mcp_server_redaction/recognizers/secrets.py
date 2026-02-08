from presidio_analyzer import Pattern, PatternRecognizer


def create_secrets_recognizers() -> list[PatternRecognizer]:
    api_key_recognizer = PatternRecognizer(
        supported_entity="API_KEY",
        name="ApiKeyRecognizer",
        patterns=[
            Pattern("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", 0.9),
            Pattern("github_token", r"\bghp_[A-Za-z0-9]{36}\b", 0.9),
            Pattern("gitlab_token", r"\bglpat-[A-Za-z0-9\-_]{20,}\b", 0.9),
            Pattern("stripe_key", r"\b[sp]k_(?:live|test)_[A-Za-z0-9]{20,}\b", 0.9),
        ],
        context=["key", "token", "api", "secret", "bearer"],
    )

    aws_key_recognizer = PatternRecognizer(
        supported_entity="AWS_ACCESS_KEY",
        name="AwsAccessKeyRecognizer",
        patterns=[
            Pattern("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.9),
        ],
        context=["aws", "key", "access"],
    )

    connection_string_recognizer = PatternRecognizer(
        supported_entity="CONNECTION_STRING",
        name="ConnectionStringRecognizer",
        patterns=[
            Pattern(
                "postgres_uri",
                r"\bpostgresql?://[^\s]+",
                0.9,
            ),
            Pattern(
                "mysql_uri",
                r"\bmysql://[^\s]+",
                0.9,
            ),
            Pattern(
                "mongodb_uri",
                r"\bmongodb(?:\+srv)?://[^\s]+",
                0.9,
            ),
        ],
        context=["database", "db", "connection", "uri", "url"],
    )

    return [api_key_recognizer, aws_key_recognizer, connection_string_recognizer]
