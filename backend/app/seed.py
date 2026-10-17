"""Fictional demo data: 3 patients, care plans, people and 3 days of history.

All names, phones and health data are invented. Phones use the 555-01xx range,
reserved for fiction.

History is shaped so code-based comparison has something to find:
- Rosa (pat_001): low appetite the last 2 shifts -> a 3rd low triggers a `change`.
- Jorge (pat_002): poor sleep 2 nights, knee pain since 2 days ago.
- Elena (pat_003): 20:00 medication skipped / not mentioned; low urination twice.
- Ana (cg_001) cares for two patients, to exercise the "which patient?" question.
- Dra. Marta (doc_001) is the doctor for all three and authored their care plans.
- Jorge has his own login (ptl_002, role patient): he can read his care plan, not reports.

Seeded reports use channel="seed" and model="seed" so they are never mistaken
for model output. Alerts are not hand-written here; compare.py produces them.

Usage (from backend/):
    python -m app.seed           # create tables, insert data if missing
    python -m app.seed --reset   # DROP all tables first (destructive)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from .models import (
    Base,
    CarePlan,
    ChecklistItem,
    ItemSource,
    Medication,
    Patient,
    PatientAccess,
    Person,
    Report,
    ReportItem,
    ReportVersion,
    Role,
    SessionLocal,
    VersionSource,
    engine,
    init_db,
)

PEOPLE = [
    ("cg_001", "+15550100001", "Ana (ficticia)"),
    ("cg_002", "+15550100002", "Bruno (ficticio)"),
    ("fam_001", "+15550100011", "Carmen (ficticia)"),
    ("fam_002", "+15550100012", "Diego (ficticio)"),
    ("fam_003", "+15550100013", "Lucía (ficticia)"),
    ("doc_001", "+15550100021", "Dra. Marta (ficticia)"),
    ("ptl_002", "+15550100031", "Jorge (ficticio)"),  # Jorge's own login
]

PATIENTS = [
    {
        "id": "pat_001",
        "display_name": "Rosa (ficticia)",
        "birth_year": 1941,
        "vocabulary": ["Rosa", "andador"],
        "access": [("cg_001", Role.caregiver), ("fam_001", Role.family), ("doc_001", Role.doctor)],
        "indications": ["Estimular la hidratación", "Acompañar al caminar"],
        "allergies": ["Penicilina"],
        "medications": [
            ("med_001", "Enalapril", "1 comprimido", ["08:00", "20:00"]),
            ("med_002", "Metformina", "1 comprimido", ["08:00"]),
        ],
    },
    {
        "id": "pat_002",
        "display_name": "Jorge (ficticio)",
        "birth_year": 1938,
        "vocabulary": ["Jorge", "andador"],
        "access": [("cg_001", Role.caregiver), ("fam_002", Role.family), ("doc_001", Role.doctor),
                   ("ptl_002", Role.patient)],
        "indications": ["Recordarle usar el andador", "Levotiroxina en ayunas"],
        "allergies": [],
        "medications": [
            ("med_003", "Levotiroxina", "1 comprimido", ["07:00"]),
            ("med_004", "Donepecilo", "1 comprimido", ["21:00"]),
        ],
    },
    {
        "id": "pat_003",
        "display_name": "Elena (ficticia)",
        "birth_year": 1945,
        "vocabulary": ["Elena"],
        "access": [("cg_002", Role.caregiver), ("fam_003", Role.family), ("doc_001", Role.doctor)],
        "indications": ["Ofrecer agua cada 2 horas", "Dieta blanda"],
        "allergies": ["Ibuprofeno"],
        "medications": [
            ("med_005", "Paracetamol", "1 comprimido", ["08:00", "14:00", "20:00"]),
            ("med_006", "Omeprazol", "1 cápsula", ["08:00"]),
        ],
    },
]


def dose(plan_ref: str, time: str, given: bool) -> dict:
    return {"plan_ref": plan_ref, "time": time, "given": given}


# (patient_id, caregiver_id, days_ago, transcript, items)
# items: {item: (value, level, quote, details)}; unlisted checklist items = not mentioned.
HISTORY = [
    (
        "pat_001", "cg_001", 3,
        "Hoy Rosa estuvo tranquila. Comió bien el almuerzo y la cena. Le di el enalapril "
        "y la metformina a las ocho, y el enalapril de la noche a las veinte. Orinó normal. "
        "Caminó por el pasillo con ayuda. No refirió dolor. Durmió la siesta bien. Sin novedades.",
        {
            "mood": ("Tranquila", "normal", "Rosa estuvo tranquila", None),
            "appetite": ("Comió bien almuerzo y cena", "normal", "Comió bien el almuerzo y la cena", None),
            "medication": (
                "Enalapril y metformina 08:00; enalapril 20:00", None,
                "Le di el enalapril y la metformina a las ocho, y el enalapril de la noche a las veinte",
                {"doses": [dose("med_001", "08:00", True), dose("med_002", "08:00", True), dose("med_001", "20:00", True)]},
            ),
            "urination": ("Normal", "normal", "Orinó normal", None),
            "mobility": ("Caminó con ayuda", "normal", "Caminó por el pasillo con ayuda", None),
            "pain": ("Sin dolor", "none", "No refirió dolor", None),
            "sleep": ("Durmió bien la siesta", "normal", "Durmió la siesta bien", None),
            "incidents": ("Sin novedades", "none", "Sin novedades", None),
        },
    ),
    (
        "pat_001", "cg_001", 2,
        "Rosa comió poco en la cena, dejó casi todo el plato. Tomó el enalapril y la metformina "
        "de las ocho y el enalapril de la noche. Orinó bien. Estuvo un poco decaída, no quiso "
        "salir al patio. No se quejó de dolor. Sin caídas.",
        {
            "appetite": ("Comió poco en la cena", "low", "comió poco en la cena, dejó casi todo el plato", None),
            "medication": (
                "Enalapril y metformina 08:00; enalapril 20:00", None,
                "Tomó el enalapril y la metformina de las ocho y el enalapril de la noche",
                {"doses": [dose("med_001", "08:00", True), dose("med_002", "08:00", True), dose("med_001", "20:00", True)]},
            ),
            "urination": ("Normal", "normal", "Orinó bien", None),
            "mood": ("Decaída", "low", "Estuvo un poco decaída, no quiso salir al patio", None),
            "pain": ("Sin dolor", "none", "No se quejó de dolor", None),
            "incidents": ("Sin caídas", "none", "Sin caídas", None),
        },
    ),
    (
        "pat_001", "cg_001", 1,
        "Otra vez casi no comió nada en la cena. Le di la metformina y el enalapril a las ocho; "
        "el de las veinte también. Durmió de corrido toda la noche. Caminó con el andador hasta "
        "el comedor. Hizo pis normal. Sin dolor. Hoy no hubo incidentes.",
        {
            "appetite": ("Casi no comió en la cena", "low", "casi no comió nada en la cena", None),
            "medication": (
                "Metformina y enalapril 08:00; enalapril 20:00", None,
                "Le di la metformina y el enalapril a las ocho; el de las veinte también",
                {"doses": [dose("med_001", "08:00", True), dose("med_002", "08:00", True), dose("med_001", "20:00", True)]},
            ),
            "sleep": ("Durmió toda la noche", "normal", "Durmió de corrido toda la noche", None),
            "mobility": ("Caminó con andador", "normal", "Caminó con el andador hasta el comedor", None),
            "urination": ("Normal", "normal", "Hizo pis normal", None),
            "pain": ("Sin dolor", "none", "Sin dolor", None),
            "incidents": ("Sin incidentes", "none", "Hoy no hubo incidentes", None),
        },
    ),
    (
        "pat_002", "cg_001", 3,
        "Jorge desayunó y almorzó todo. La levotiroxina se la di a las siete en ayunas y el "
        "donepecilo a las nueve de la noche. Durmió mal, se despertó varias veces. Estuvo de buen "
        "humor. Usó el andador sin problema. Orinó normal. No tuvo dolor. Sin incidentes.",
        {
            "appetite": ("Comió todo", "normal", "desayunó y almorzó todo", None),
            "medication": (
                "Levotiroxina 07:00; donepecilo 21:00", None,
                "La levotiroxina se la di a las siete en ayunas y el donepecilo a las nueve de la noche",
                {"doses": [dose("med_003", "07:00", True), dose("med_004", "21:00", True)]},
            ),
            "sleep": ("Durmió mal, varios despertares", "poor", "Durmió mal, se despertó varias veces", None),
            "mood": ("Buen humor", "normal", "Estuvo de buen humor", None),
            "mobility": ("Andador sin problema", "normal", "Usó el andador sin problema", None),
            "urination": ("Normal", "normal", "Orinó normal", None),
            "pain": ("Sin dolor", "none", "No tuvo dolor", None),
            "incidents": ("Sin incidentes", "none", "Sin incidentes", None),
        },
    ),
    (
        "pat_002", "cg_001", 2,
        "Comió bien. Le di la levotiroxina a las siete. El donepecilo de la noche lo tomó a las "
        "nueve. Otra noche que durmió mal, estuvo inquieto de madrugada. Le dolía la rodilla "
        "derecha al caminar. Sin caídas.",
        {
            "appetite": ("Comió bien", "normal", "Comió bien", None),
            "medication": (
                "Levotiroxina 07:00; donepecilo 21:00", None,
                "Le di la levotiroxina a las siete. El donepecilo de la noche lo tomó a las nueve",
                {"doses": [dose("med_003", "07:00", True), dose("med_004", "21:00", True)]},
            ),
            "sleep": ("Durmió mal, inquieto", "poor", "Otra noche que durmió mal, estuvo inquieto de madrugada", None),
            "pain": ("Dolor en rodilla derecha al caminar", "present", "Le dolía la rodilla derecha al caminar", None),
            "incidents": ("Sin caídas", "none", "Sin caídas", None),
        },
    ),
    (
        "pat_002", "cg_001", 1,
        "Jorge comió normal. Tomó la levotiroxina a las siete y el donepecilo a las nueve. Esta "
        "noche durmió mejor. Seguía con un poco de dolor en la rodilla. Caminó despacio con el "
        "andador. Orinó bien. Estuvo conversador. Ningún incidente.",
        {
            "appetite": ("Comió normal", "normal", "comió normal", None),
            "medication": (
                "Levotiroxina 07:00; donepecilo 21:00", None,
                "Tomó la levotiroxina a las siete y el donepecilo a las nueve",
                {"doses": [dose("med_003", "07:00", True), dose("med_004", "21:00", True)]},
            ),
            "sleep": ("Durmió mejor", "normal", "Esta noche durmió mejor", None),
            "pain": ("Algo de dolor en la rodilla", "present", "Seguía con un poco de dolor en la rodilla", None),
            "mobility": ("Caminó despacio con andador", "reduced", "Caminó despacio con el andador", None),
            "urination": ("Normal", "normal", "Orinó bien", None),
            "mood": ("Conversador", "normal", "Estuvo conversador", None),
            "incidents": ("Sin incidentes", "none", "Ningún incidente", None),
        },
    ),
    (
        "pat_003", "cg_002", 3,
        "Elena almorzó bien la dieta blanda. Le di el omeprazol y el paracetamol a las ocho, el "
        "paracetamol de las catorce y el de las veinte. Tomó bastante agua y orinó normal. Durmió "
        "bien. Estuvo contenta, recibió visita. Caminó en el jardín. Sin dolor. Sin incidentes.",
        {
            "appetite": ("Almorzó bien", "normal", "almorzó bien la dieta blanda", None),
            "medication": (
                "Omeprazol y paracetamol 08:00; paracetamol 14:00 y 20:00", None,
                "Le di el omeprazol y el paracetamol a las ocho, el paracetamol de las catorce y el de las veinte",
                {"doses": [dose("med_006", "08:00", True), dose("med_005", "08:00", True),
                           dose("med_005", "14:00", True), dose("med_005", "20:00", True)]},
            ),
            "urination": ("Normal", "normal", "orinó normal", None),
            "sleep": ("Durmió bien", "normal", "Durmió bien", None),
            "mood": ("Contenta", "normal", "Estuvo contenta", None),
            "mobility": ("Caminó en el jardín", "normal", "Caminó en el jardín", None),
            "pain": ("Sin dolor", "none", "Sin dolor", None),
            "incidents": ("Sin incidentes", "none", "Sin incidentes", None),
        },
    ),
    (
        "pat_003", "cg_002", 2,
        "Comió todo. Omeprazol y paracetamol a las ocho, paracetamol a las catorce. A las veinte "
        "no le di el paracetamol porque estaba dormida. Orinó poco. Estuvo tranquila. Sin dolor. "
        "Sin novedades.",
        {
            "appetite": ("Comió todo", "normal", "Comió todo", None),
            "medication": (
                "08:00 y 14:00 dadas; 20:00 no se dio (dormida)", None,
                "Omeprazol y paracetamol a las ocho, paracetamol a las catorce. A las veinte no le di el paracetamol porque estaba dormida",
                {"doses": [dose("med_006", "08:00", True), dose("med_005", "08:00", True),
                           dose("med_005", "14:00", True), dose("med_005", "20:00", False)]},
            ),
            "urination": ("Orinó poco", "low", "Orinó poco", None),
            "mood": ("Tranquila", "normal", "Estuvo tranquila", None),
            "pain": ("Sin dolor", "none", "Sin dolor", None),
            "incidents": ("Sin novedades", "none", "Sin novedades", None),
        },
    ),
    (
        "pat_003", "cg_002", 1,
        "Elena comió poco. Le di el omeprazol y el paracetamol de las ocho y el de las catorce. "
        "Orinó poco otra vez. Estuvo algo desorientada a la tarde. Durmió la siesta. Sin dolor. "
        "Caminó un poco por el pasillo. Sin caídas.",
        {
            "appetite": ("Comió poco", "low", "comió poco", None),
            "medication": (
                "Omeprazol y paracetamol 08:00; paracetamol 14:00", None,
                "Le di el omeprazol y el paracetamol de las ocho y el de las catorce",
                {"doses": [dose("med_006", "08:00", True), dose("med_005", "08:00", True),
                           dose("med_005", "14:00", True)]},
            ),
            "urination": ("Orinó poco", "low", "Orinó poco otra vez", None),
            "mood": ("Algo desorientada a la tarde", "confused", "Estuvo algo desorientada a la tarde", None),
            "sleep": ("Durmió la siesta", "normal", "Durmió la siesta", None),
            "pain": ("Sin dolor", "none", "Sin dolor", None),
            "mobility": ("Caminó un poco", "normal", "Caminó un poco por el pasillo", None),
            "incidents": ("Sin caídas", "none", "Sin caídas", None),
        },
    ),
]


def shift_end(days_ago: int) -> datetime:
    """Evening shift end (20:30 at UTC-3) `days_ago` days before today."""
    today = datetime.now(timezone.utc).replace(hour=23, minute=30, second=0, microsecond=0)
    return today - timedelta(days=days_ago)


def seed() -> None:
    init_db()
    with SessionLocal.begin() as s:
        if s.get(Patient, "pat_001") is not None:
            print("Seed data already present; nothing to do. Use --reset to recreate.")
            return

        for pid, phone, name in PEOPLE:
            s.add(Person(id=pid, phone=phone, display_name=name))

        for p in PATIENTS:
            s.add(Patient(id=p["id"], display_name=p["display_name"],
                          birth_year=p["birth_year"], vocabulary=p["vocabulary"]))
            for person_id, role in p["access"]:
                s.add(PatientAccess(person_id=person_id, patient_id=p["id"], role=role))
            plan = CarePlan(id=f"plan_{p['id'][4:]}", patient_id=p["id"], version=1,
                            created_by="doc_001",
                            indications=p["indications"], allergies=p["allergies"])
            s.add(plan)
            for med_id, name, dose_text, times in p["medications"]:
                s.add(Medication(id=med_id, care_plan_id=plan.id, name=name,
                                 dose_text=dose_text, times=times))

        for n, (patient_id, caregiver_id, days_ago, transcript, items) in enumerate(HISTORY, 1):
            at = shift_end(days_ago)
            report = Report(id=f"rep_{n:03d}", patient_id=patient_id, caregiver_id=caregiver_id,
                            message_id=f"seed-{n:03d}", channel="seed", transcript=transcript,
                            created_at=at)
            version = ReportVersion(id=f"rv_{n:03d}_1", report=report, version=1,
                                    source=VersionSource.original, created_by=caregiver_id,
                                    model="seed", created_at=at)
            s.add_all([report, version])
            for item in ChecklistItem:
                value, level, quote, details = items.get(item.value, (None, None, None, None))
                if quote is not None and quote.casefold() not in transcript.casefold():
                    raise ValueError(f"rep_{n:03d}: quote for {item.value} not in transcript: {quote!r}")
                s.add(ReportItem(report_version=version, item=item, value=value, level=level,
                                 details=details, quote=quote,
                                 quote_verified=True if quote is not None else None,
                                 source=ItemSource.transcript))

    print(f"Seeded {len(PEOPLE)} people, {len(PATIENTS)} patients, {len(HISTORY)} reports.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)
        print("Dropped all tables.")
    seed()
