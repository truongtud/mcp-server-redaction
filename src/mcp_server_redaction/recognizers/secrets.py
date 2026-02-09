from presidio_analyzer import Pattern, PatternRecognizer


def create_secrets_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="API_KEY",
            name="ApiKeyRecognizer",
            patterns=[
                Pattern("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", 0.9),
                Pattern("github_token", r"\bghp_[A-Za-z0-9]{36}\b", 0.9),
                Pattern("gitlab_token", r"\bglpat-[A-Za-z0-9\-_]{20,}\b", 0.9),
                Pattern("stripe_key", r"\b[sp]k_(?:live|test)_[A-Za-z0-9]{20,}\b", 0.9),
                Pattern("gcp_api_key", r"\bAIzaSy[A-Za-z0-9_-]{33}\b", 0.9),
                Pattern("slack_token", r"\bxox[bpoas]-[A-Za-z0-9\-]{10,250}\b", 0.9),
                Pattern("jwt_token", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", 0.9),
            ],
            context=["key", "token", "api", "secret", "bearer", "authorization"],
        ),
        PatternRecognizer(
            supported_entity="AWS_ACCESS_KEY",
            name="AwsAccessKeyRecognizer",
            patterns=[
                Pattern("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.9),
            ],
            context=["aws", "key", "access"],
        ),
        PatternRecognizer(
            supported_entity="CONNECTION_STRING",
            name="ConnectionStringRecognizer",
            patterns=[
                Pattern("postgres_uri", r"\bpostgresql?://[^\s]+", 0.9),
                Pattern("mysql_uri", r"\bmysql://[^\s]+", 0.9),
                Pattern("mongodb_uri", r"\bmongodb(?:\+srv)?://[^\s]+", 0.9),
                Pattern("redis_uri", r"\brediss?://[^\s]+", 0.9),
            ],
            context=["database", "db", "connection", "uri", "url"],
        ),
        PatternRecognizer(
            supported_entity="SSH_PRIVATE_KEY",
            name="SshPrivateKeyRecognizer",
            patterns=[
                Pattern(
                    "ssh_private_key_header",
                    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
                    0.95,
                ),
            ],
            context=["key", "ssh", "private"],
        ),
    ]
