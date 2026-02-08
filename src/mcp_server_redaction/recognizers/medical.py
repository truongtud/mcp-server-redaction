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

    return [icd10_recognizer, mrn_recognizer, drug_recognizer]
