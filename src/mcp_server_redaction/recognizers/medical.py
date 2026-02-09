from presidio_analyzer import Pattern, PatternRecognizer


_COMMON_DRUGS = [
    "Metformin", "Lisinopril", "Amlodipine", "Metoprolol", "Atorvastatin",
    "Omeprazole", "Losartan", "Albuterol", "Gabapentin", "Hydrochlorothiazide",
    "Sertraline", "Simvastatin", "Montelukast", "Escitalopram", "Rosuvastatin",
    "Bupropion", "Furosemide", "Pantoprazole", "Duloxetine", "Prednisone",
    "Amoxicillin", "Azithromycin", "Ibuprofen", "Acetaminophen", "Aspirin",
    "Warfarin", "Clopidogrel", "Insulin", "Levothyroxine", "Fluoxetine",
]


def create_medical_recognizers() -> list[PatternRecognizer]:
    icd10_recognizer = PatternRecognizer(
        supported_entity="ICD10_CODE",
        name="Icd10Recognizer",
        patterns=[
            Pattern("icd10", r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b", 0.6),
        ],
        context=["diagnosis", "icd", "code", "dx", "condition"],
    )

    mrn_recognizer = PatternRecognizer(
        supported_entity="MEDICAL_RECORD_NUMBER",
        name="MrnRecognizer",
        patterns=[
            Pattern("mrn_dashes", r"\b\d{3}-\d{3}-\d{3}\b", 0.4),
            Pattern("mrn_plain", r"\b\d{7,10}\b", 0.2),
        ],
        context=["mrn", "medical record", "patient id", "chart"],
    )

    drug_recognizer = PatternRecognizer(
        supported_entity="DRUG_NAME",
        name="DrugNameRecognizer",
        deny_list=_COMMON_DRUGS,
        context=["taking", "prescribed", "medication", "drug", "dose", "mg", "daily"],
    )

    npi_recognizer = PatternRecognizer(
        supported_entity="NPI_NUMBER",
        name="NpiRecognizer",
        patterns=[
            Pattern("npi", r"\b\d{10}\b", 0.3),
        ],
        context=["npi", "provider", "national provider", "prescriber"],
    )

    dea_recognizer = PatternRecognizer(
        supported_entity="DEA_NUMBER",
        name="DeaRecognizer",
        patterns=[
            Pattern("dea", r"\b[A-Z]{2}\d{7}\b", 0.6),
        ],
        context=["dea", "prescriber", "controlled substance", "schedule"],
    )

    insurance_id_recognizer = PatternRecognizer(
        supported_entity="INSURANCE_ID",
        name="InsuranceIdRecognizer",
        patterns=[
            Pattern("insurance_alphanum", r"\b[A-Z]{2,4}[-]?\d{6,12}\b", 0.4),
            Pattern("policy_number", r"\bPOL[-]?\d{4}[-]?\d{5,10}\b", 0.7),
            Pattern("claim_number", r"\bCLM[-]?\d{4}[-]?\d{5,10}\b", 0.7),
        ],
        context=[
            "insurance", "policy", "claim", "member", "subscriber",
            "group", "coverage", "id", "number",
        ],
    )

    return [
        icd10_recognizer, mrn_recognizer, drug_recognizer,
        npi_recognizer, dea_recognizer, insurance_id_recognizer,
    ]
