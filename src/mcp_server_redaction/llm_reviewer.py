import json
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a PII (Personally Identifiable Information) detection expert. Your job is to find sensitive entities in text that automated tools may have missed.

You look for ALL types of PII including but not limited to:
- Names (any language/culture), ages, dates of birth
- Addresses, postal codes, GPS coordinates
- Phone numbers, email addresses, URLs with PII
- Government IDs (SSN, passport, driver's license, national IDs from any country)
- Financial data (account numbers, policy numbers, claim numbers, tax IDs)
- Medical data (patient IDs, diagnoses, medications, provider numbers)
- Biometric identifiers
- Vehicle registration, license plates
- Usernames, passwords, security questions/answers
- Any identifier that could link back to a specific individual

You support ALL languages: English, German, French, Vietnamese, Spanish, etc.

Respond ONLY with a JSON array. Each element must have:
- "text": the exact substring from the input
- "entity_type": one of PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS, DATE_OF_BIRTH, AGE, US_SSN, PASSPORT, DRIVER_LICENSE, NATIONAL_ID, TAX_ID, INSURANCE_ID, MEDICAL_CONDITION, DRUG_NAME, CREDIT_CARD, IBAN, IP_ADDRESS, USERNAME, LICENSE_PLATE, or a descriptive ALL_CAPS type.

If no additional PII is found, respond with: []"""


class LLMReviewer:
    def __init__(self, model: str = "llama3.1", enabled: bool = True):
        self._model = model
        self._enabled = enabled

    @staticmethod
    def is_available() -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            import ollama
            models = ollama.list()
            return any("llama3.1" in m.model for m in models.models)
        except Exception:
            return False

    def review(self, text: str, already_found: list[str]) -> list[dict]:
        """Ask the LLM to find PII that existing layers missed.

        Args:
            text: The original text to review.
            already_found: List of entity text values already detected by L1/L2.

        Returns:
            List of dicts with keys: text, entity_type, start, end
        """
        if not self._enabled:
            return []

        try:
            import ollama
        except ImportError:
            logger.warning("ollama package not installed")
            return []

        already_str = ", ".join(f'"{v}"' for v in already_found) if already_found else "none"
        user_prompt = (
            f"The following entities were already detected: [{already_str}]\n\n"
            f"Find any ADDITIONAL PII in this text that was missed:\n\n{text}"
        )

        try:
            response = ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0},
            )
        except Exception:
            logger.exception("Ollama LLM review failed")
            return []

        return self._parse_response(response.message.content, text)

    def _parse_response(self, content: str, original_text: str) -> list[dict]:
        """Parse LLM JSON response and locate entities in the original text."""
        # Extract JSON array from response (LLM may wrap in markdown)
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return []

        try:
            entities = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")
            return []

        if not isinstance(entities, list):
            return []

        result = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            text_val = entity.get("text", "")
            entity_type = entity.get("entity_type", "UNKNOWN")
            if not text_val:
                continue

            # Find the entity position in original text
            start = original_text.find(text_val)
            if start == -1:
                continue
            end = start + len(text_val)

            result.append({
                "text": text_val,
                "entity_type": entity_type,
                "start": start,
                "end": end,
            })

        return result
