"""Replace the clinical content of a C-CDA document with made-up data from fixed tables.

``anonymize`` removes identity. ``synthesize`` runs it first and then rewrites
each section so the document keeps its structure (sections, entries, templates,
ids, status codes and time shapes) but none of its clinical content. Every
choice comes from a generator seeded with the seed, so the same seed gives
byte-identical output. No network, no model.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .anonymize import SUBSTITUTES, AnonymizeReport, anonymize
from .document import CdaDocument, Section, parse_xml
from .mappers._shared import statement_of
from .sections import KNOWN_UNMAPPED, find_spec
from .xml import NSMAP, SDTC_NS, attr, child, children, find, local_name, q, text_of, xsi_type

SNOMED = "2.16.840.1.113883.6.96"
LOINC = "2.16.840.1.113883.6.1"
RXNORM = "2.16.840.1.113883.6.88"
CVX = "2.16.840.1.113883.12.292"
ICD10CM = "2.16.840.1.113883.6.90"
CPT = "2.16.840.1.113883.6.12"
NCI = "2.16.840.1.113883.3.26.1.1"
UNII = "2.16.840.1.113883.4.9"
CDC_RACE = "2.16.840.1.113883.6.238"
ADMINISTRATIVE_GENDER = "2.16.840.1.113883.5.1"
_SYSTEM_NAMES = {
    SNOMED: "SNOMED CT",
    LOINC: "LOINC",
    RXNORM: "RxNorm",
    CVX: "CVX",
    ICD10CM: "ICD-10-CM",
    CPT: "CPT",
    NCI: "NCI Thesaurus",
    UNII: "UNII",
    CDC_RACE: "CDC Race and Ethnicity",
}

REMOVED = "Removed"
NARRATIVE_REMOVED = "Narrative removed."
NEVER_SMOKER = ("266919005", "Never smoker")
BODY_SITE = ("123037004", "Body structure")
UNKNOWN_VALUE = ("261665006", "Unknown")
OTHER_RACE = ("2131-1", "Other Race")
NOT_HISPANIC = ("2186-5", "Not Hispanic or Latino")
ORAL = ("C38288", "Oral")
INTRAMUSCULAR = ("C28161", "Intramuscular")
_HEADER = ("Name", "Code", "Date", "Value")

# (RxNorm code, display, dose value, dose unit, route code, route display, sig)
DRUGS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    (
        "314076",
        "lisinopril 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "617310",
        "atorvastatin 20 MG Oral Tablet",
        "20",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth at bedtime.",
    ),
    (
        "259255",
        "atorvastatin 80 MG Oral Tablet",
        "80",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth at bedtime.",
    ),
    (
        "312961",
        "simvastatin 20 MG Oral Tablet",
        "20",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth at bedtime.",
    ),
    (
        "861007",
        "metformin hydrochloride 500 MG Oral Tablet",
        "500",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth twice daily with meals.",
    ),
    (
        "860975",
        "24 HR metformin hydrochloride 500 MG Extended Release Oral Tablet",
        "500",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily with the evening meal.",
    ),
    (
        "197361",
        "amlodipine 5 MG Oral Tablet",
        "5",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "308136",
        "amlodipine 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "310798",
        "hydrochlorothiazide 25 MG Oral Tablet",
        "25",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth every morning.",
    ),
    (
        "429503",
        "hydrochlorothiazide 12.5 MG Oral Tablet",
        "12.5",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth every morning.",
    ),
    (
        "866924",
        "metoprolol tartrate 25 MG Oral Tablet",
        "25",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth twice daily.",
    ),
    (
        "979480",
        "losartan potassium 50 MG Oral Tablet",
        "50",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "313988",
        "furosemide 40 MG Oral Tablet",
        "40",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth every morning.",
    ),
    (
        "243670",
        "aspirin 81 MG Oral Tablet",
        "81",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "309362",
        "clopidogrel 75 MG Oral Tablet",
        "75",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "855332",
        "warfarin sodium 5 MG Oral Tablet",
        "5",
        "mg",
        *ORAL,
        "Take as directed by the anticoagulation clinic.",
    ),
    (
        "314200",
        "pantoprazole 40 MG Delayed Release Oral Tablet",
        "40",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily before breakfast.",
    ),
    (
        "966247",
        "levothyroxine sodium 0.1 MG Oral Tablet",
        "0.1",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth every morning on an empty stomach.",
    ),
    (
        "310489",
        "glipizide 5 MG Oral Tablet",
        "5",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily before breakfast.",
    ),
    (
        "106892",
        "insulin, isophane 70 UNT/ML / regular 30 UNT/ML Injectable Suspension",
        "20",
        "[IU]",
        "C38299",
        "Subcutaneous",
        "Inject 20 units under the skin twice daily.",
    ),
    (
        "312940",
        "sertraline 50 MG Oral Tablet",
        "50",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "310385",
        "fluoxetine 20 MG Oral Capsule",
        "20",
        "mg",
        *ORAL,
        "Take 1 capsule by mouth every morning.",
    ),
    (
        "351250",
        "escitalopram 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "309314",
        "citalopram 20 MG Oral Tablet",
        "20",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "310431",
        "gabapentin 300 MG Oral Capsule",
        "300",
        "mg",
        *ORAL,
        "Take 1 capsule by mouth three times daily.",
    ),
    (
        "198440",
        "acetaminophen 500 MG Oral Tablet",
        "1000",
        "mg",
        *ORAL,
        "Take 2 tablets by mouth every 6 hours as needed for pain.",
    ),
    (
        "310965",
        "ibuprofen 200 MG Oral Tablet",
        "400",
        "mg",
        *ORAL,
        "Take 2 tablets by mouth every 8 hours as needed for pain.",
    ),
    (
        "849574",
        "naproxen sodium 220 MG Oral Tablet",
        "220",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth twice daily with food as needed.",
    ),
    (
        "152923",
        "meloxicam 15 MG Oral Tablet",
        "15",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily with food.",
    ),
    (
        "312617",
        "prednisone 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily for 5 days.",
    ),
    (
        "308182",
        "amoxicillin 250 MG Oral Capsule",
        "250",
        "mg",
        *ORAL,
        "Take 1 capsule by mouth three times daily for 10 days.",
    ),
    (
        "562251",
        "amoxicillin 250 MG / clavulanate 125 MG Oral Tablet",
        "1",
        "{tbl}",
        *ORAL,
        "Take 1 tablet by mouth twice daily for 7 days.",
    ),
    (
        "308460",
        "azithromycin 250 MG Oral Tablet",
        "250",
        "mg",
        *ORAL,
        "Take 2 tablets on day 1, then 1 tablet daily for 4 days.",
    ),
    (
        "309309",
        "ciprofloxacin 500 MG Oral Tablet",
        "500",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth twice daily for 7 days.",
    ),
    (
        "309097",
        "cefuroxime 250 MG Oral Tablet",
        "250",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth twice daily for 10 days.",
    ),
    (
        "834061",
        "penicillin V potassium 250 MG Oral Tablet",
        "250",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth four times daily for 10 days.",
    ),
    (
        "745752",
        "200 ACTUAT albuterol 0.09 MG/ACTUAT Metered Dose Inhaler",
        "2",
        "{puff}",
        "C38216",
        "Respiratory (inhalation)",
        "Inhale 2 puffs by mouth every 4 to 6 hours as needed.",
    ),
    (
        "895994",
        "120 ACTUAT fluticasone propionate 0.044 MG/ACTUAT Metered Dose Inhaler",
        "2",
        "{puff}",
        "C38216",
        "Respiratory (inhalation)",
        "Inhale 2 puffs by mouth twice daily.",
    ),
    (
        "200224",
        "montelukast 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth at bedtime.",
    ),
    (
        "311372",
        "loratadine 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily as needed.",
    ),
    (
        "1014678",
        "cetirizine hydrochloride 10 MG Oral Tablet",
        "10",
        "mg",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
    (
        "1000126",
        "1 ML medroxyprogesterone acetate 150 MG/ML Injection",
        "150",
        "mg",
        *INTRAMUSCULAR,
        "Inject 1 mL into the muscle every 3 months.",
    ),
    (
        "999967",
        "amlodipine 5 MG / hydrochlorothiazide 12.5 MG / olmesartan medoxomil 20 MG Oral Tablet",
        "1",
        "{tbl}",
        *ORAL,
        "Take 1 tablet by mouth once daily.",
    ),
)

# (SNOMED CT code, display, ICD-10-CM code, ICD-10-CM display)
CONDITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("59621000", "Essential hypertension", "I10", "Essential (primary) hypertension"),
    (
        "44054006",
        "Type 2 diabetes mellitus",
        "E11.9",
        "Type 2 diabetes mellitus without complications",
    ),
    (
        "46635009",
        "Type 1 diabetes mellitus",
        "E10.9",
        "Type 1 diabetes mellitus without complications",
    ),
    ("15777000", "Prediabetes", "R73.03", "Prediabetes"),
    ("55822004", "Hyperlipidemia", "E78.5", "Hyperlipidemia, unspecified"),
    ("195967001", "Asthma", "J45.909", "Unspecified asthma, uncomplicated"),
    (
        "13645005",
        "Chronic obstructive lung disease",
        "J44.9",
        "Chronic obstructive pulmonary disease, unspecified",
    ),
    (
        "35489007",
        "Depressive disorder",
        "F32.9",
        "Major depressive disorder, single episode, unspecified",
    ),
    ("197480006", "Anxiety disorder", "F41.9", "Anxiety disorder, unspecified"),
    ("193462001", "Insomnia", "G47.00", "Insomnia, unspecified"),
    ("73430006", "Sleep apnea", "G47.30", "Sleep apnea, unspecified"),
    ("40055000", "Chronic sinusitis", "J32.9", "Chronic sinusitis, unspecified"),
    ("444814009", "Viral sinusitis", "J01.90", "Acute sinusitis, unspecified"),
    ("10509002", "Acute bronchitis", "J20.9", "Acute bronchitis, unspecified"),
    ("195662009", "Acute viral pharyngitis", "J02.9", "Acute pharyngitis, unspecified"),
    ("43878008", "Streptococcal sore throat", "J02.0", "Streptococcal pharyngitis"),
    ("65363002", "Otitis media", "H66.90", "Otitis media, unspecified, unspecified ear"),
    ("233604007", "Pneumonia", "J18.9", "Pneumonia, unspecified organism"),
    (
        "6142004",
        "Influenza",
        "J11.1",
        "Influenza due to unidentified influenza virus with other respiratory manifestations",
    ),
    (
        "68566005",
        "Urinary tract infectious disease",
        "N39.0",
        "Urinary tract infection, site not specified",
    ),
    ("396275006", "Osteoarthritis", "M19.90", "Unspecified osteoarthritis, unspecified site"),
    ("239873007", "Osteoarthritis of knee", "M17.9", "Osteoarthritis of knee, unspecified"),
    (
        "64859006",
        "Osteoporosis",
        "M81.0",
        "Age-related osteoporosis without current pathological fracture",
    ),
    ("279039007", "Low back pain", "M54.50", "Low back pain, unspecified"),
    ("90560007", "Gout", "M10.9", "Gout, unspecified"),
    ("40930008", "Hypothyroidism", "E03.9", "Hypothyroidism, unspecified"),
    (
        "235595009",
        "Gastroesophageal reflux disease",
        "K21.9",
        "Gastro-esophageal reflux disease without esophagitis",
    ),
    ("70153002", "Hemorrhoids", "K64.9", "Unspecified hemorrhoids"),
    ("68496003", "Polyp of colon", "K63.5", "Polyp of colon"),
    ("74400008", "Appendicitis", "K35.80", "Unspecified acute appendicitis"),
    ("271737000", "Anemia", "D64.9", "Anemia, unspecified"),
    ("49436004", "Atrial fibrillation", "I48.91", "Unspecified atrial fibrillation"),
    (
        "414545008",
        "Ischemic heart disease",
        "I25.10",
        "Atherosclerotic heart disease of native coronary artery without angina pectoris",
    ),
    ("22298006", "Myocardial infarction", "I21.9", "Acute myocardial infarction, unspecified"),
    ("84114007", "Heart failure", "I50.9", "Heart failure, unspecified"),
    ("230690007", "Cerebrovascular accident", "I63.9", "Cerebral infarction, unspecified"),
    ("431855005", "Chronic kidney disease stage 1", "N18.1", "Chronic kidney disease, stage 1"),
    ("162864005", "Body mass index 30+ - obesity", "E66.9", "Obesity, unspecified"),
    ("237602007", "Metabolic syndrome X", "E88.81", "Metabolic syndrome"),
    (
        "37796009",
        "Migraine",
        "G43.909",
        "Migraine, unspecified, not intractable, without status migrainosus",
    ),
    ("25064002", "Headache", "R51.9", "Headache, unspecified"),
    ("24079001", "Atopic dermatitis", "L20.9", "Atopic dermatitis, unspecified"),
    ("367498001", "Seasonal allergic rhinitis", "J30.2", "Other seasonal allergic rhinitis"),
    ("386661006", "Fever", "R50.9", "Fever, unspecified"),
    ("49727002", "Cough", "R05.9", "Cough, unspecified"),
)

# (display, RxNorm code, UNII code, SNOMED CT code, allergy type code, allergy type display)
ALLERGENS: tuple[tuple[str, str | None, str | None, str, str, str], ...] = (
    ("Penicillin G", "7980", "Q42T66VG0C", "6369005", "416098002", "Drug allergy"),
    ("Amoxicillin", "723", "804826J2HU", "372687004", "416098002", "Drug allergy"),
    ("Aspirin", "1191", "R16CO5Y76E", "387458008", "416098002", "Drug allergy"),
    ("Ibuprofen", "5640", "WK2XYI10QM", "387207008", "416098002", "Drug allergy"),
    ("Codeine", "2670", "Q830PW7520", "387494007", "416098002", "Drug allergy"),
    ("Morphine", "7052", "76I7G6D29C", "373529000", "416098002", "Drug allergy"),
    ("Sulfamethoxazole", "10180", "JE42381TNV", "387467008", "416098002", "Drug allergy"),
    ("Erythromycin", "4053", "63937KV33D", "372694001", "416098002", "Drug allergy"),
    ("Acetaminophen", "161", "362O9ITL9D", "387517004", "416098002", "Drug allergy"),
    ("Peanut", None, None, "256349002", "414285001", "Food allergy"),
    ("Egg", None, None, "102263004", "414285001", "Food allergy"),
    ("Cow's milk", None, None, "3718001", "414285001", "Food allergy"),
    ("Shellfish", None, None, "735029006", "414285001", "Food allergy"),
    ("Wheat", None, None, "412071004", "414285001", "Food allergy"),
    ("Animal dander", None, None, "264287008", "232347008", "Dander (animal) allergy"),
    ("House dust mite", None, None, "260147004", "419199007", "Allergy to substance"),
    ("Grass pollen", None, None, "256277009", "419199007", "Allergy to substance"),
    ("Mold", None, None, "84489001", "419199007", "Allergy to substance"),
    ("Latex", None, None, "111088007", "419199007", "Allergy to substance"),
)

# (SNOMED CT code, display)
REACTIONS: tuple[tuple[str, str], ...] = (
    ("247472004", "Hives"),
    ("271807003", "Rash"),
    ("267036007", "Dyspnea"),
    ("422587007", "Nausea"),
    ("422400008", "Vomiting"),
    ("62315008", "Diarrhea"),
    ("39579001", "Anaphylaxis"),
    ("418290006", "Itching"),
    ("25064002", "Headache"),
    ("65124004", "Swelling"),
    ("49727002", "Cough"),
)
SEVERITIES: tuple[tuple[str, str], ...] = (
    ("255604002", "Mild"),
    ("6736007", "Moderate"),
    ("24484000", "Severe"),
)

# (CVX code, display)
VACCINES: tuple[tuple[str, str], ...] = (
    ("140", "Influenza, seasonal, injectable, preservative free"),
    ("141", "Influenza, seasonal, injectable"),
    ("150", "Influenza, injectable, quadrivalent, preservative free"),
    ("158", "Influenza, injectable, quadrivalent"),
    ("115", "Tdap"),
    ("113", "Td (adult), preservative free"),
    ("08", "Hep B, adolescent or pediatric"),
    ("43", "Hep B, adult"),
    ("83", "Hep A, ped/adol, 2 dose"),
    ("52", "Hep A, adult"),
    ("03", "MMR"),
    ("21", "varicella"),
    ("10", "IPV"),
    ("20", "DTaP"),
    ("49", "Hib (PRP-OMP)"),
    ("133", "Pneumococcal conjugate PCV 13"),
    ("33", "pneumococcal polysaccharide PPV23"),
    ("121", "zoster live"),
    ("187", "zoster recombinant"),
    ("62", "HPV, quadrivalent"),
    ("165", "HPV9"),
    ("208", "COVID-19, mRNA, LNP-S, PF, 30 mcg/0.3 mL dose"),
    ("207", "COVID-19, mRNA, LNP-S, PF, 100 mcg/0.5 mL dose"),
    ("116", "rotavirus, pentavalent"),
    ("114", "meningococcal MCV4P"),
)

# (CPT code or None, SNOMED CT code, display)
PROCEDURES: tuple[tuple[str | None, str, str], ...] = (
    ("45378", "73761001", "Colonoscopy"),
    ("43235", "423827005", "Endoscopy"),
    ("93000", "29303009", "Electrocardiographic procedure"),
    ("93306", "40701008", "Echocardiography"),
    ("94010", "23426006", "Measurement of respiratory function"),
    ("71046", "399208008", "Plain chest X-ray"),
    ("77067", "24623002", "Screening mammography"),
    ("76700", "45036003", "Ultrasonography of abdomen"),
    ("70450", "303653007", "Computed tomography of head"),
    ("70551", "241615005", "Magnetic resonance imaging of brain"),
    ("36415", "396550006", "Blood test"),
    ("87081", "117015009", "Throat culture"),
    ("81025", "252160004", "Standard pregnancy test"),
    ("90471", "33879002", "Administration of vaccine"),
    ("96372", "76601001", "Intramuscular injection"),
    ("95115", "180256009", "Subcutaneous immunotherapy"),
    ("12001", "288086009", "Suture open wound"),
    ("58300", "65200003", "Insertion of intrauterine contraceptive device"),
    ("47562", "38102005", "Cholecystectomy"),
    ("44950", "80146002", "Appendectomy"),
    ("27447", "609588000", "Total knee replacement"),
    ("27130", "52734007", "Total hip replacement"),
    ("66984", "110473004", "Cataract surgery"),
    ("33533", "232717009", "Coronary artery bypass grafting"),
    ("92928", "415070008", "Percutaneous coronary intervention"),
    ("97110", "91251008", "Physical therapy procedure"),
    ("92014", "36228007", "Ophthalmic examination and evaluation"),
    ("99406", "225323000", "Smoking cessation education"),
    ("96127", "171207006", "Depression screening"),
    (None, "430193006", "Medication reconciliation"),
    (None, "710824005", "Assessment of health and social care needs"),
    (None, "162673000", "General examination of patient"),
    (None, "269911007", "Sputum examination"),
)

# (LOINC code, display, unit, low, high, decimals)
LAB_TESTS: tuple[tuple[str, str, str, float, float, int], ...] = (
    ("6690-2", "Leukocytes [#/volume] in Blood by Automated count", "10*3/uL", 4.0, 10.5, 1),
    ("789-8", "Erythrocytes [#/volume] in Blood by Automated count", "10*6/uL", 4.0, 5.5, 2),
    ("718-7", "Hemoglobin [Mass/volume] in Blood", "g/dL", 12.0, 16.0, 1),
    ("4544-3", "Hematocrit [Volume Fraction] of Blood by Automated count", "%", 36.0, 46.0, 1),
    ("787-2", "MCV [Entitic volume] by Automated count", "fL", 80.0, 100.0, 1),
    ("785-6", "MCH [Entitic mass] by Automated count", "pg", 27.0, 33.0, 1),
    ("786-4", "MCHC [Mass/volume] by Automated count", "g/dL", 32.0, 36.0, 1),
    (
        "21000-5",
        "Erythrocyte distribution width [Entitic volume] by Automated count",
        "fL",
        39.0,
        46.0,
        1,
    ),
    ("777-3", "Platelets [#/volume] in Blood by Automated count", "10*3/uL", 150, 400, 0),
    (
        "32623-1",
        "Platelet mean volume [Entitic volume] in Blood by Automated count",
        "fL",
        9.0,
        12.0,
        1,
    ),
    ("2345-7", "Glucose [Mass/volume] in Serum or Plasma", "mg/dL", 70, 99, 0),
    ("2339-0", "Glucose [Mass/volume] in Blood", "mg/dL", 70, 99, 0),
    ("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma", "mg/dL", 7, 20, 0),
    ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL", 0.6, 1.2, 2),
    ("33914-3", "Glomerular filtration rate/1.73 sq M.predicted", "mL/min/{1.73_m2}", 60, 120, 0),
    ("2951-2", "Sodium [Moles/volume] in Serum or Plasma", "mmol/L", 136, 145, 0),
    ("2823-3", "Potassium [Moles/volume] in Serum or Plasma", "mmol/L", 3.5, 5.1, 1),
    ("2075-0", "Chloride [Moles/volume] in Serum or Plasma", "mmol/L", 98, 107, 0),
    ("2028-9", "Carbon dioxide, total [Moles/volume] in Serum or Plasma", "mmol/L", 22, 29, 0),
    ("17861-6", "Calcium [Mass/volume] in Serum or Plasma", "mg/dL", 8.6, 10.3, 1),
    ("2601-3", "Magnesium [Mass/volume] in Serum or Plasma", "mg/dL", 1.7, 2.3, 1),
    ("2777-1", "Phosphate [Mass/volume] in Serum or Plasma", "mg/dL", 2.5, 4.5, 1),
    ("2885-2", "Protein [Mass/volume] in Serum or Plasma", "g/dL", 6.4, 8.3, 1),
    ("1751-7", "Albumin [Mass/volume] in Serum or Plasma", "g/dL", 3.5, 5.0, 1),
    ("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", "mg/dL", 0.2, 1.2, 1),
    (
        "6768-6",
        "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma",
        "U/L",
        40,
        120,
        0,
    ),
    (
        "1742-6",
        "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
        "U/L",
        7,
        40,
        0,
    ),
    (
        "1920-8",
        "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
        "U/L",
        10,
        40,
        0,
    ),
    ("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "mg/dL", 120, 199, 0),
    ("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma", "mg/dL", 50, 149, 0),
    ("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "mg/dL", 40, 80, 0),
    (
        "13457-7",
        "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation",
        "mg/dL",
        50,
        99,
        0,
    ),
    ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "%", 4.0, 5.6, 1),
    ("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma", "m[IU]/L", 0.4, 4.0, 2),
    ("3024-7", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma", "ng/dL", 0.8, 1.8, 2),
    ("2276-4", "Ferritin [Mass/volume] in Serum or Plasma", "ng/mL", 20, 200, 0),
    ("2498-4", "Iron [Mass/volume] in Serum or Plasma", "ug/dL", 50, 150, 0),
    ("2132-9", "Cobalamin (Vitamin B12) [Mass/volume] in Serum or Plasma", "pg/mL", 200, 900, 0),
    ("1989-3", "25-hydroxyvitamin D3 [Mass/volume] in Serum or Plasma", "ng/mL", 30, 80, 0),
    ("3084-1", "Urate [Mass/volume] in Serum or Plasma", "mg/dL", 3.5, 7.0, 1),
    ("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma", "mg/L", 0.0, 5.0, 1),
    ("10839-9", "Troponin I.cardiac [Mass/volume] in Serum or Plasma", "ng/mL", 0.00, 0.03, 2),
    ("5902-2", "Prothrombin time (PT)", "s", 11.0, 13.5, 1),
    ("6301-6", "INR in Platelet poor plasma by Coagulation assay", "{INR}", 0.9, 1.1, 1),
    ("14959-1", "Microalbumin/Creatinine [Mass Ratio] in Urine", "mg/g", 0, 30, 0),
)
LAB_BY_CODE = {t[0]: t for t in LAB_TESTS}

# (LOINC code, display, test LOINC codes)
LAB_PANELS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "58410-2",
        "CBC panel - Blood by Automated count",
        (
            "6690-2",
            "789-8",
            "718-7",
            "4544-3",
            "787-2",
            "785-6",
            "786-4",
            "21000-5",
            "777-3",
            "32623-1",
        ),
    ),
    (
        "24323-8",
        "Comprehensive metabolic 2000 panel - Serum or Plasma",
        (
            "2345-7",
            "3094-0",
            "2160-0",
            "2951-2",
            "2823-3",
            "2075-0",
            "2028-9",
            "17861-6",
            "2885-2",
            "1751-7",
            "1975-2",
            "6768-6",
            "1742-6",
            "1920-8",
        ),
    ),
    (
        "24321-2",
        "Basic metabolic 2000 panel - Serum or Plasma",
        ("2345-7", "3094-0", "2160-0", "2951-2", "2823-3", "2075-0", "2028-9", "17861-6"),
    ),
    (
        "57698-3",
        "Lipid panel with direct LDL - Serum or Plasma",
        ("2093-3", "2571-8", "2085-9", "13457-7"),
    ),
    (
        "55231-5",
        "Electrolytes 2000 panel - Serum or Plasma",
        ("2951-2", "2823-3", "2075-0", "2028-9"),
    ),
    (
        "24325-3",
        "Hepatic function 2000 panel - Serum or Plasma",
        ("2885-2", "1751-7", "1975-2", "6768-6", "1742-6", "1920-8"),
    ),
    (
        "24362-6",
        "Renal function 2000 panel - Serum or Plasma",
        (
            "2345-7",
            "3094-0",
            "2160-0",
            "2951-2",
            "2823-3",
            "2075-0",
            "2028-9",
            "17861-6",
            "2777-1",
            "1751-7",
        ),
    ),
)

# (LOINC code, display, text value) for observations whose value is a string
LAB_TEXT: tuple[tuple[str, str, str], ...] = (
    ("600-7", "Bacteria identified in Blood by Culture", "No growth"),
    ("630-4", "Bacteria identified in Urine by Culture", "No growth"),
    ("5778-6", "Color of Urine", "Yellow"),
    ("5767-9", "Appearance of Urine", "Clear"),
    ("20454-5", "Protein [Presence] in Urine by Test strip", "Negative"),
    ("5792-7", "Glucose [Presence] in Urine by Test strip", "Negative"),
    ("48767-8", "Annotation comment", "No comment"),
)
# (LOINC code, display, SNOMED CT value code, value display) for coded values
LAB_CODED: tuple[tuple[str, str, str, str], ...] = (
    ("882-1", "ABO and Rh group [Type] in Blood", "278149003", "Blood group O Rh(D) positive"),
    ("883-9", "ABO group [Type] in Blood", "58460004", "Blood group O"),
    ("10331-7", "Rh [Type] in Blood", "165747007", "RhD positive"),
    (
        "94500-6",
        "SARS-CoV-2 RNA [Presence] in Respiratory specimen by NAA with probe detection",
        "260385009",
        "Negative",
    ),
)

# LOINC code -> ((unit, low, high, decimals), ...); the first variant is the default
VITALS: dict[str, tuple[tuple[str, float, float, int], ...]] = {
    "8480-6": (("mm[Hg]", 104, 128, 0),),
    "8462-4": (("mm[Hg]", 62, 82, 0),),
    "8478-0": (("mm[Hg]", 75, 95, 0),),
    "8867-4": (("/min", 60, 92, 0), ("{beats}/min", 60, 92, 0)),
    "9279-1": (("/min", 12, 18, 0), ("{breaths}/min", 12, 18, 0)),
    "8310-5": (("Cel", 36.4, 37.2, 1), ("[degF]", 97.5, 98.9, 1)),
    "2708-6": (("%", 95, 100, 0),),
    "59408-5": (("%", 95, 100, 0),),
    "39156-5": (("kg/m2", 20.0, 27.0, 1),),
    "59576-9": (("%", 10, 90, 0),),
    "77606-2": (("%", 10, 90, 0),),
    "8289-1": (("%", 10, 90, 0),),
    "8287-5": (("cm", 52.0, 58.0, 1), ("[in_i]", 20.5, 22.8, 1)),
    "9843-4": (("cm", 52.0, 58.0, 1), ("[in_i]", 20.5, 22.8, 1)),
    "72514-3": (("{score}", 0, 3, 0),),
}
_HEIGHT_CODES = frozenset({"8302-2", "3137-7", "8306-3"})
_WEIGHT_CODES = frozenset({"29463-7", "3141-9"})
SMOKING_LOINC = "72166-2"
_SMOKING_TEMPLATE = "2.16.840.1.113883.10.20.22.4.78"
_SMOKING_VALUES = frozenset(
    {
        "449868002",
        "428041000124106",
        "8517006",
        "266919005",
        "77176002",
        "266927001",
        "428071000124103",
        "428061000124105",
    }
)
# LOINC code -> (low, high, decimals) for numeric social history values
SOCIAL_VALUES: dict[str, tuple[float, float, int]] = {
    "74013-4": (0, 1, 0),
    "11287-0": (0, 1, 0),
    "63512-8": (1, 4, 0),
}

# Codes that describe the record rather than the patient; they are kept everywhere.
GENERIC_CODES = frozenset(
    {
        "ASSERTION",
        "CONC",
        "SEV",
        "IMMUNIZ",
        "55607006",
        "64572001",
        "404684003",
        "282291009",
        "409586006",
        "418799008",
        "248536006",
        "373930000",
        "33999-4",
        "82606-5",
        "75323-6",
        "75326-9",
        "46680005",
        "74728-7",
        "55561003",
        "73425007",
        "413322009",
        "7087005",
        "255227004",
        "246455001",
        "277022003",
        "419199007",
        "416098002",
        "414285001",
        "232347008",
        "59037007",
        "235719002",
        "420134006",
        "418038007",
        "419511003",
        "418471000",
        "8319008",
        "48765-2",
        "10160-0",
    }
)
_GENERIC_SYSTEMS = frozenset(
    {
        "2.16.840.1.113883.6.238",
        "2.16.840.1.113883.6.101",
        "2.16.840.1.113883.6.259",
        "2.16.840.1.113883.6.8",
        "2.16.840.1.113883.4.642.4.1",
    }
)
_GENERIC_SYSTEM_PREFIXES = (
    "2.16.840.1.113883.5.",
    "2.16.840.1.113883.1.11.",
    "2.16.840.1.113883.11.",
    "2.16.840.1.113883.12.",
)
_GENERIC_LOCALS = frozenset(
    {
        "statusCode",
        "interpretationCode",
        "priorityCode",
        "administrativeGenderCode",
        "realmCode",
        "languageCode",
        "confidentialityCode",
        "functionCode",
        "dischargeDispositionCode",
        "maritalStatusCode",
        "raceCode",
        "ethnicGroupCode",
        "religiousAffiliationCode",
        "modeCode",
        "proficiencyLevelCode",
    }
)
_CODED_TYPES = frozenset({"CD", "CE", "CO", "CV"})
_TIMING_TYPES = frozenset({"PIVL_TS", "EIVL_TS", "SXPR_TS"})
_CONTENT_NAME_PARENTS = frozenset(
    {"manufacturedMaterial", "labeledDrug", "manufacturerOrganization"}
)
_FAMILY_HISTORY = "2.16.840.1.113883.10.20.22.2.15"
_VALUE_LIKE = re.compile(r"^[\d.,:/+\-T ]*\d[\d.,:/+\-T ]*(?:\s+\S+)?$")
_SNOMED_TEXT = re.compile(r"^SNOMED-?\s?CT\s+\d+", re.IGNORECASE)


@dataclass(slots=True)
class SynthesizeReport:
    """What was replaced, per section, and what a reviewer should still look at."""

    anonymize: AnonymizeReport
    entries_replaced: dict[str, int] = field(default_factory=dict)
    """Entries rewritten, keyed by section code."""
    unrecognized_sections: list[dict] = field(default_factory=list)
    """Sections neither mapped nor known: ``code``, ``title`` and ``entries`` each."""
    residual_findings: list[str] = field(default_factory=list)
    """Original text that survived rewriting, with its location."""

    def to_dict(self) -> dict:
        return {
            "anonymize": self.anonymize.to_dict(),
            "entries_replaced": dict(self.entries_replaced),
            "unrecognized_sections": [dict(u) for u in self.unrecognized_sections],
            "residual_findings": list(self.residual_findings),
        }

    def summary(self) -> str:
        """One line for a terminal."""
        return (
            f"sections {len(self.entries_replaced)}, "
            f"entries replaced {sum(self.entries_replaced.values())}, "
            f"unrecognized sections {len(self.unrecognized_sections)}, "
            f"residual findings {len(self.residual_findings)}; "
            f"anonymize: {self.anonymize.summary()}"
        )


def synthesize(xml_bytes: bytes, *, seed: str | None = None) -> tuple[bytes, SynthesizeReport]:
    """Anonymize, then replace all clinical content. The same seed gives the same output."""
    seed = seed if seed is not None else secrets.token_hex(16)
    scrubbed, anon_report = anonymize(xml_bytes, seed=seed)
    root = parse_xml(scrubbed)
    worker = _Synthesizer(seed, SynthesizeReport(anonymize=anon_report))
    worker.run(root)
    tree = root.getroottree()
    out = etree.tostring(tree, xml_declaration=True, encoding=tree.docinfo.encoding or "UTF-8")
    return out, worker.report


def synthesize_file(src: Path, dst: Path, seed: str | None = None) -> SynthesizeReport:
    """Synthesize one XML file into another."""
    out, report = synthesize(Path(src).read_bytes(), seed=seed)
    Path(dst).write_bytes(out)
    return report


@dataclass(slots=True)
class _Row:
    """One narrative table row; ``ids`` are narrative IDs to put on the cells."""

    cells: list[str]
    ids: list[str | None]
    extra: list[str] = field(default_factory=list)


class _Synthesizer:
    def __init__(self, seed: str, report: SynthesizeReport) -> None:
        self.seed = seed
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self.rng = random.Random(int.from_bytes(digest, "big"))
        self.report = report
        self.tokens: set[str] = set()
        self.emitted: set[str] = {REMOVED, NARRATIVE_REMOVED, *_HEADER, *SUBSTITUTES}
        self.kept_codes: set[tuple[str | None, str]] = set()
        self.placed_ids: set[str] = set()
        self.height_cm: float | None = None
        self.weight_kg: float | None = None

    def run(self, root: etree._Element) -> None:
        self._demographics(root)
        self._specialties(root)
        sections = CdaDocument(root, "<synthesize>").sections()
        for section in sections:
            self._collect_tokens(section)
        for section in sections:
            self._rewrite_section(section)
        self._find_residuals(root)

    # ---- header -------------------------------------------------------------------

    def _demographics(self, root: etree._Element) -> None:
        """Neutralize race, ethnicity, religion, marital status, gender and birth year."""
        years = [y for v in _effective_times(root) if (y := _year(v)) is not None]
        latest = max(years, default=None)
        for patient in root.iterfind("c:recordTarget/c:patientRole/c:patient", namespaces=NSMAP):
            for el in (*children(patient, "raceCode"), *children(patient, "raceCode", SDTC_NS)):
                self._set_code(el, CDC_RACE, *OTHER_RACE)
            for el in children(patient, "ethnicGroupCode"):
                self._set_code(el, CDC_RACE, *NOT_HISPANIC)
            for el in children(patient, "religiousAffiliationCode"):
                for name in ("code", "codeSystem", "codeSystemName", "displayName"):
                    el.attrib.pop(name, None)
                el.set("nullFlavor", "UNK")
            for el in children(patient, "maritalStatusCode"):
                el.set("code", "U")
                if el.get("displayName") is not None:
                    el.set("displayName", self._emit("Unknown"))
            gender = child(patient, "administrativeGenderCode")
            if gender is not None and attr(gender, "code") is None:
                gender.attrib.pop("nullFlavor", None)
                gender.set("code", "UN")
                gender.set("codeSystem", ADMINISTRATIVE_GENDER)
                gender.set("displayName", self._emit("Undifferentiated"))
                for ot in children(gender, "originalText"):
                    gender.remove(ot)
            birth = child(patient, "birthTime")
            raw = attr(birth, "value")
            if raw and len(raw) >= 4 and raw[:4].isdigit():
                base = latest if latest is not None else int(raw[:4])
                year = base - self.rng.randint(25, 70)
                rest = "0101" + raw[8:] if len(raw) >= 8 else raw[4:]
                birth.set("value", f"{year:04d}{rest}")

    def _specialties(self, root: etree._Element) -> None:
        """Keep provider specialty codes but drop their text and display names."""
        for entity in root.iter(q("assignedEntity")):
            code_el = child(entity, "code")
            if code_el is None:
                continue
            self._set_original_text(code_el, REMOVED)
            for el in (code_el, *children(code_el, "translation")):
                if el.get("displayName") is not None:
                    el.set("displayName", REMOVED)

    # ---- helpers ------------------------------------------------------------------

    def _hash(self, original: str) -> str:
        return hashlib.sha256((self.seed + original).encode("utf-8")).hexdigest()[:12]

    def _draw(self, low: float, high: float, decimals: int) -> str:
        if decimals == 0:
            return str(self.rng.randint(math.ceil(low), math.floor(high)))
        return _fmt(self.rng.uniform(low, high), decimals)

    def _emit(self, text: str) -> str:
        self.emitted.add(text)
        return text

    def _keep_code(self, el: etree._Element | None) -> None:
        """Record a code (and its translations) as deliberately kept."""
        if el is None:
            return
        code = attr(el, "code")
        if code:
            self.kept_codes.add((attr(el, "codeSystem"), code))
        display = attr(el, "displayName")
        if display:
            self.emitted.add(display)
        for tr in children(el, "translation"):
            self._keep_code(tr)

    def _set_code(
        self,
        el: etree._Element,
        system: str,
        code: str,
        display: str,
        alternates: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """Rewrite a coded element; translations follow the primary or ``alternates``."""
        el.set("code", code)
        el.set("codeSystem", system)
        if el.get("displayName") is not None:
            el.set("displayName", display)
        if el.get("codeSystemName") is not None:
            name = _SYSTEM_NAMES.get(system)
            if name:
                el.set("codeSystemName", name)
            else:
                del el.attrib["codeSystemName"]
        self.kept_codes.add((system, code))
        self.emitted.add(display)
        for tr in children(el, "translation"):
            tsys = attr(tr, "codeSystem")
            if attr(tr, "code") is None:
                continue
            if alternates and tsys in alternates:
                self._set_code(tr, tsys, *alternates[tsys])
            elif tsys == system or tsys is None:
                self._set_code(tr, system, code, display)

    def _hash_code(self, el: etree._Element) -> None:
        code = attr(el, "code") or ""
        el.set("code", self._hash(code))
        if el.get("displayName") is not None:
            el.set("displayName", REMOVED)
        self.kept_codes.add((attr(el, "codeSystem"), el.get("code") or ""))

    def _set_text_el(self, el: etree._Element | None, text: str) -> str | None:
        """Set an entry text element; a narrative reference is kept and its ID returned."""
        if el is None:
            return None
        ref = child(el, "reference")
        if ref is not None:
            el.text = None
            for c in list(el):
                if c is not ref:
                    el.remove(c)
            ref.tail = None
            return _ref_id(ref)
        _set_plain_text(el, self._emit(text))
        return None

    def _set_text(self, parent: etree._Element | None, text: str) -> str | None:
        return self._set_text_el(child(parent, "text"), text)

    def _set_original_text(self, code_el: etree._Element | None, text: str) -> str | None:
        return self._set_text_el(child(code_el, "originalText"), text)

    def _set_normal(self, ic: etree._Element) -> None:
        if attr(ic, "code") is None:
            return
        ic.set("code", "N")
        if ic.get("displayName") is not None:
            ic.set("displayName", self._emit("Normal"))

    def _condition(self, el: etree._Element) -> tuple[str, str, str, str]:
        """Replace a condition value with a table entry, in the system the original used."""
        snomed, display, icd, icd_display = self.rng.choice(CONDITIONS)
        alternates = {SNOMED: (snomed, display), ICD10CM: (icd, icd_display)}
        if attr(el, "codeSystem") == ICD10CM:
            self._set_code(el, ICD10CM, icd, icd_display, alternates)
        else:
            self._set_code(el, SNOMED, snomed, display, alternates)
        self._set_original_text(el, display)
        return snomed, display, icd, icd_display

    def _placeholder(self, el: etree._Element) -> None:
        """Replace a clinical code the section handler did not cover."""
        local = local_name(el)
        system = attr(el, "codeSystem")
        parent = el.getparent()
        is_value = local == "value" or (
            local == "translation" and parent is not None and local_name(parent) == "value"
        )
        if local in {"targetSiteCode", "approachSiteCode"}:
            self._set_code(el, SNOMED, *BODY_SITE)
        elif local == "routeCode":
            self._set_code(el, NCI, *ORAL)
        elif system in {SNOMED, ICD10CM} and is_value:
            self._condition(el)
        elif system == RXNORM:
            drug = self.rng.choice(DRUGS)
            self._set_code(el, RXNORM, drug[0], drug[1])
        elif system == CVX:
            self._set_code(el, CVX, *self.rng.choice(VACCINES))
        elif system == LOINC:
            test = self.rng.choice(LAB_TESTS)
            self._set_code(el, LOINC, test[0], test[1])
        elif system == CPT:
            cpt, snomed, display = self.rng.choice([p for p in PROCEDURES if p[0]])
            self._set_code(el, CPT, cpt or "", display, {SNOMED: (snomed, display)})
        elif system == SNOMED:
            cpt, snomed, display = self.rng.choice(PROCEDURES)
            alternates = {CPT: (cpt, display)} if cpt else None
            self._set_code(el, SNOMED, snomed, display, alternates)
        elif system == ICD10CM:
            self._condition(el)
        else:
            self._hash_code(el)

    # ---- tokens seen before rewriting ----------------------------------------------

    def _collect_tokens(self, section: Section) -> None:
        text_el = child(section.element, "text")
        if text_el is not None:
            for node in text_el.iter():
                if isinstance(node.tag, str):
                    self._token(node.text)
                    self._token(node.tail)
        for entry in section.entries:
            for node in entry.iter():
                if not isinstance(node.tag, str):
                    continue
                local = local_name(node)
                display = attr(node, "displayName")
                if display and not _is_generic(node):
                    self._token(display)
                if local in {"text", "originalText", "value", "lotNumberText", "desc"} or (
                    local == "name" and _content_name(node)
                ):
                    self._token(text_of(node))

    def _token(self, text: str | None) -> None:
        if not text:
            return
        s = " ".join(text.split())
        if len(s) < 3 or _VALUE_LIKE.match(s):
            return
        self.tokens.add(s)

    # ---- sections -------------------------------------------------------------------

    def _rewrite_section(self, section: Section) -> None:
        spec = find_spec(section)
        key = section.code or (spec.loinc if spec else section.title) or "?"
        entries = section.entries
        self.report.entries_replaced[key] = self.report.entries_replaced.get(key, 0) + len(entries)
        if spec is None:
            if section.code not in KNOWN_UNMAPPED:
                self.report.unrecognized_sections.append(
                    {"code": section.code, "title": section.title, "entries": len(entries)}
                )
            self._blank_section(section)
            return
        handler = getattr(self, _HANDLERS[spec.loinc])
        rows: list[_Row] = []
        for entry in entries:
            refs = _refs(entry)
            entry_rows = handler(entry)
            self._sweep_entry(entry)
            if not entry_rows:
                entry_rows = [_Row([REMOVED, "", _date(statement_of(entry)), ""], [None] * 4)]
            used = {i for r in entry_rows for i in r.ids if i}
            entry_rows[-1].extra.extend(r for r in refs if r not in used)
            rows.extend(entry_rows)
        self._rebuild_narrative(section, rows)

    def _blank_section(self, section: Section) -> None:
        family = section.code == "10157-6" or _FAMILY_HISTORY in section.template_ids
        text_el = child(section.element, "text")
        if text_el is not None:
            _clear(text_el)
            etree.SubElement(text_el, q("paragraph")).text = NARRATIVE_REMOVED
        for entry in section.entries:
            self._blank_entry(entry, family)

    def _blank_entry(self, entry: etree._Element, family: bool) -> None:
        for node in entry.iter():
            if not isinstance(node.tag, str):
                continue
            local = local_name(node)
            code = attr(node, "code")
            if (
                code is not None
                and not _is_generic(node)
                and (attr(node, "codeSystem"), code) not in self.kept_codes
            ):
                parent = node.getparent()
                is_value = local == "value" or (
                    local == "translation" and parent is not None and local_name(parent) == "value"
                )
                if family and is_value and attr(node, "codeSystem") in {SNOMED, ICD10CM}:
                    self._condition(node)
                else:
                    self._hash_code(node)
            if local in {"text", "originalText", "desc"}:
                _set_plain_text(node, REMOVED)
            elif local == "value" and code is None and attr(node, "value") is None:
                if text_of(node):
                    _set_plain_text(node, REMOVED)
            elif local == "name" and _content_name(node):
                self._blank_name(node)
            elif local == "lotNumberText" and node.text:
                node.text = self._hash(node.text)

    def _sweep_entry(self, entry: etree._Element) -> None:
        """Replace whatever content the section handler left behind in an entry."""
        for node in entry.iter():
            if not isinstance(node.tag, str):
                continue
            local = local_name(node)
            code = attr(node, "code")
            if (
                code is not None
                and not _is_generic(node)
                and (attr(node, "codeSystem"), code) not in self.kept_codes
            ):
                self._placeholder(node)
            if local in {"text", "originalText"}:
                self._scrub_text(node)
            elif local == "value" and code is None and attr(node, "value") is None:
                text = text_of(node)
                if text and text not in self.emitted:
                    _set_plain_text(node, REMOVED)
            elif local == "desc":
                _set_plain_text(node, REMOVED)
            elif local == "name" and _content_name(node):
                if text_of(node) not in self.emitted:
                    self._blank_name(node)
            elif local == "lotNumberText" and node.text and node.text not in self.emitted:
                node.text = self._emit(self._hash(node.text))

    def _scrub_text(self, el: etree._Element) -> None:
        ref = child(el, "reference")
        if ref is not None:
            self._set_text_el(el, "")
            return
        text = text_of(el)
        if text and text not in self.emitted:
            _set_plain_text(el, REMOVED)

    def _blank_name(self, name_el: etree._Element) -> None:
        parent = name_el.getparent()
        if parent is not None and local_name(parent) == "manufacturerOrganization":
            _clear(name_el)
        else:
            _set_plain_text(name_el, REMOVED)

    # ---- section handlers ---------------------------------------------------------------

    def _medications(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        for sa in entry.iter(q("substanceAdministration")):
            rxcui, display, dose, dose_unit, route, route_display, sig = self.rng.choice(DRUGS)
            material = find(sa, "c:consumable/c:manufacturedProduct/c:manufacturedMaterial")
            code_el = child(material, "code")
            name_id = None
            if code_el is not None and attr(code_el, "code") is not None:
                self._set_code(code_el, RXNORM, rxcui, display)
                name_id = self._set_original_text(code_el, display)
            name_el = child(material, "name")
            if name_el is not None and text_of(name_el):
                _set_plain_text(name_el, self._emit(display))
            dq = child(sa, "doseQuantity")
            if dq is not None and attr(dq, "value") is not None:
                dq.set("value", dose)
                dq.set("unit", dose_unit)
            rc = child(sa, "routeCode")
            if rc is not None and attr(rc, "code") is not None:
                self._set_code(rc, NCI, route, route_display)
            sig_id = self._set_text(sa, sig)
            self.emitted.add(sig)
            rows.append(
                _Row([display, f"RxNorm {rxcui}", _date(sa), sig], [name_id, None, None, sig_id])
            )
        return rows

    def _problems(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        stmt = statement_of(entry)
        for obs in entry.iter(q("observation")):
            value = child(obs, "value")
            if value is None or attr(value, "code") is None or _is_generic(value):
                continue
            snomed, display, icd, _ = self._condition(value)
            ot_id = _ref_id(find(value, "c:originalText/c:reference"))
            text_id = self._set_text(obs, display)
            date = _date(obs) or _date(stmt)
            rows.append(
                _Row(
                    [display, f"SNOMED CT {snomed}", date, f"ICD-10-CM {icd}"],
                    [text_id, ot_id, None, None],
                )
            )
        return rows

    def _allergies(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        stmt = statement_of(entry)
        for obs in entry.iter(q("observation")):
            playing = find(obs, "c:participant/c:participantRole/c:playingEntity")
            substance = child(playing, "code")
            if substance is None:
                continue
            name = self._emit("No known allergies")
            label = ""
            name_id = None
            if attr(substance, "code") is not None:
                name, label, alternates = self._allergen(substance)
                name_id = self._set_original_text(substance, name)
                name_el = child(playing, "name")
                if name_el is not None and text_of(name_el):
                    _set_plain_text(name_el, name)
                value = child(obs, "value")
                if value is not None and attr(value, "code") is not None:
                    self._set_code(value, SNOMED, *alternates["type"])
            reaction = severity = ""
            for nested in obs.iter(q("observation")):
                if nested is obs:
                    continue
                nested_value = child(nested, "value")
                if nested_value is None or attr(nested_value, "code") is None:
                    continue
                templates = {attr(t, "root") for t in children(nested, "templateId")}
                parent = nested.getparent()
                if "2.16.840.1.113883.10.20.22.4.8" in templates or (
                    attr(child(nested, "code"), "code") == "SEV"
                ):
                    sev = self.rng.choice(SEVERITIES)
                    self._set_code(nested_value, SNOMED, *sev)
                    self._set_text(nested, sev[1])
                    severity = severity or sev[1]
                elif "2.16.840.1.113883.10.20.22.4.9" in templates or (
                    parent is not None and (attr(parent, "typeCode") or "").upper() == "MFST"
                ):
                    rxn = self.rng.choice(REACTIONS)
                    self._set_code(nested_value, SNOMED, *rxn)
                    self._set_original_text(nested_value, rxn[1])
                    self._set_text(nested, rxn[1])
                    reaction = reaction or rxn[1]
            text_id = self._set_text(obs, name)
            shown = reaction + (f" ({severity})" if severity else "")
            date = _date(obs) or _date(stmt)
            rows.append(_Row([name, label, date, shown], [text_id, name_id, None, None]))
        return rows

    def _allergen(self, substance: etree._Element) -> tuple[str, str, dict]:
        system = attr(substance, "codeSystem")
        index = {RXNORM: 1, UNII: 2}.get(system or "", 3)
        pick = self.rng.choice([a for a in ALLERGENS if a[index]])
        display, rxnorm, unii, snomed, type_code, type_display = pick
        alternates = {SNOMED: (snomed, display)}
        if rxnorm:
            alternates[RXNORM] = (rxnorm, display)
        if unii:
            alternates[UNII] = (unii, display)
        use_system = system if index != 3 else SNOMED
        code = str(pick[index])
        self._set_code(substance, use_system or SNOMED, code, display, alternates)
        alternates["type"] = (type_code, type_display)
        return display, f"{_SYSTEM_NAMES.get(use_system or '', 'code')} {code}", alternates

    def _immunizations(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        for sa in entry.iter(q("substanceAdministration")):
            cvx, display = self.rng.choice(VACCINES)
            product = find(sa, "c:consumable/c:manufacturedProduct")
            material = child(product, "manufacturedMaterial")
            code_el = child(material, "code")
            name_id = None
            if code_el is not None and attr(code_el, "code") is not None:
                self._set_code(code_el, CVX, cvx, display)
                name_id = self._set_original_text(code_el, display)
            name_el = child(material, "name")
            if name_el is not None and text_of(name_el):
                _set_plain_text(name_el, self._emit(display))
            lot = child(material, "lotNumberText")
            if lot is not None and lot.text:
                lot.text = self._emit(self._hash(lot.text))
            for org in children(product, "manufacturerOrganization"):
                for name in children(org, "name"):
                    _clear(name)
            rc = child(sa, "routeCode")
            if rc is not None and attr(rc, "code") is not None:
                self._set_code(rc, NCI, *INTRAMUSCULAR)
            for site in children(sa, "approachSiteCode"):
                if attr(site, "code") is not None:
                    self._set_code(site, SNOMED, *BODY_SITE)
            dq = child(sa, "doseQuantity")
            if dq is not None and attr(dq, "value") is not None:
                dq.set("value", "0.5")
                dq.set("unit", "mL")
            text_id = self._set_text(sa, display)
            negated = (attr(sa, "negationInd") or "").lower() == "true"
            status = self._emit("Not given" if negated else "Given")
            rows.append(
                _Row([display, f"CVX {cvx}", _date(sa), status], [text_id, name_id, None, None])
            )
        return rows

    def _procedures(self, entry: etree._Element) -> list[_Row]:
        stmt = statement_of(entry)
        if stmt is None or local_name(stmt) not in {"procedure", "act", "observation"}:
            return []
        code_el = child(stmt, "code")
        if code_el is None or attr(code_el, "code") is None:
            return []
        system = attr(code_el, "codeSystem")
        if system == CPT:
            cpt, snomed, display = self.rng.choice([p for p in PROCEDURES if p[0]])
            self._set_code(code_el, CPT, cpt or "", display, {SNOMED: (snomed, display)})
            label = f"CPT {cpt}"
        else:
            cpt, snomed, display = self.rng.choice(PROCEDURES)
            alternates = {CPT: (cpt, display)} if cpt else None
            self._set_code(code_el, SNOMED, snomed, display, alternates)
            label = f"SNOMED CT {snomed}"
        ot_id = self._set_original_text(code_el, display)
        text_id = self._set_text(stmt, display)
        for site in children(stmt, "targetSiteCode"):
            if attr(site, "code") is not None:
                self._set_code(site, SNOMED, *BODY_SITE)
        return [_Row([display, label, _date(stmt), ""], [text_id, ot_id, None, None])]

    def _results(self, entry: etree._Element) -> list[_Row]:
        stmt = statement_of(entry)
        if stmt is None:
            return []
        if local_name(stmt) == "observation":
            return [self._lab_observation(stmt, None, 0, _date(stmt))]
        if local_name(stmt) != "organizer":
            return []
        loinc, display, tests = self.rng.choice(LAB_PANELS)
        code_el = child(stmt, "code")
        ot_id = None
        if code_el is not None and attr(code_el, "code") is not None:
            self._set_code(code_el, LOINC, loinc, display)
            ot_id = self._set_original_text(code_el, display)
        self.emitted.add(display)
        date = _date(stmt)
        rows = [_Row([display, f"LOINC {loinc}", date, ""], [ot_id, None, None, None])]
        comps = [o for c in children(stmt, "component") for o in children(c, "observation")]
        panel = tuple(LAB_BY_CODE[t] for t in tests)
        for i, obs in enumerate(comps):
            rows.append(self._lab_observation(obs, panel, i, _date(obs) or date))
        return rows

    def _lab_observation(
        self,
        obs: etree._Element,
        panel: tuple[tuple[str, str, str, float, float, int], ...] | None,
        index: int,
        date: str,
    ) -> _Row:
        value = child(obs, "value")
        kind = xsi_type(value) if value is not None else None
        live = value is not None and attr(value, "nullFlavor") is None
        test = None
        extra: list[str] = []
        if live and kind == "ST":
            loinc, display, text = self.rng.choice(LAB_TEXT)
            _set_plain_text(value, self._emit(text))
            shown = text
        elif live and kind in _CODED_TYPES:
            loinc, display, vcode, vdisplay = self.rng.choice(LAB_CODED)
            self._set_code(value, SNOMED, vcode, vdisplay)
            ref = self._set_original_text(value, vdisplay)
            if ref:
                extra.append(ref)
            shown = vdisplay
        else:
            test = panel[index % len(panel)] if panel else self.rng.choice(LAB_TESTS)
            loinc, display, unit, low, high, decimals = test
            shown = ""
            if live and attr(value, "value") is not None:
                number = self._draw(low, high, 0 if kind == "INT" else decimals)
                value.set("value", number)
                if kind == "PQ" or value.get("unit") is not None:
                    value.set("unit", unit)
                shown = f"{number} {unit} (normal {_fmt(low, decimals)} - {_fmt(high, decimals)})"
            elif live and kind == "IVL_PQ":
                for local, bound in (("low", low), ("high", high)):
                    b = child(value, local)
                    if b is not None and attr(b, "value") is not None:
                        b.set("value", _fmt(bound, decimals))
                        b.set("unit", unit)
                shown = f"{_fmt(low, decimals)} - {_fmt(high, decimals)} {unit}"
            elif live and text_of(value):
                _set_plain_text(value, REMOVED)
        code_el = child(obs, "code")
        ot_id = None
        if code_el is not None and attr(code_el, "code") is not None:
            self._set_code(code_el, LOINC, loinc, display)
            ot_id = self._set_original_text(code_el, display)
        self.emitted.add(display)
        text_id = self._set_text(obs, display)
        for ic in children(obs, "interpretationCode"):
            self._set_normal(ic)
        range_id = self._set_reference_ranges(obs, test)
        self.emitted.add(shown)
        return _Row(
            [display, f"LOINC {loinc}", date, shown], [text_id, ot_id, None, range_id], extra
        )

    def _set_reference_ranges(self, obs: etree._Element, test: tuple | None) -> str | None:
        range_id = None
        for rr in children(obs, "referenceRange"):
            orange = child(rr, "observationRange")
            if orange is None:
                continue
            label = "Normal"
            value = child(orange, "value")
            if value is not None:
                for local, position in (("low", 3), ("high", 4)):
                    b = child(value, local)
                    if b is None:
                        continue
                    if test is None:
                        b.attrib.pop("value", None)
                        b.attrib.pop("unit", None)
                        b.set("nullFlavor", "NA")
                    else:
                        b.set("value", _fmt(test[position], test[5]))
                        b.set("unit", test[2])
                if test is not None:
                    label = f"{_fmt(test[3], test[5])} - {_fmt(test[4], test[5])} {test[2]}"
            rid = self._set_text(orange, label)
            range_id = range_id or rid
            for ic in children(orange, "interpretationCode"):
                self._set_normal(ic)
        return range_id

    def _vitals(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        stmt = statement_of(entry)
        for obs in _observations(stmt):
            code_el = child(obs, "code")
            self._keep_code(code_el)
            loinc = attr(code_el, "code") or ""
            display = attr(code_el, "displayName") or self._emit("Vital sign")
            value = child(obs, "value")
            shown = ""
            if value is not None and attr(value, "nullFlavor") is None:
                if loinc == SMOKING_LOINC or attr(value, "code") in _SMOKING_VALUES:
                    shown = self._never_smoker(value)
                elif attr(value, "value") is not None:
                    number, unit = self._vital_value(loinc, attr(value, "unit"), value.get("value"))
                    value.set("value", number)
                    if unit:
                        value.set("unit", unit)
                    shown = f"{number} {unit or ''}".strip()
                elif attr(value, "code") is None and text_of(value):
                    _set_plain_text(value, REMOVED)
            ot_id = self._set_original_text(code_el, display)
            text_id = self._set_text(obs, display)
            for ic in children(obs, "interpretationCode"):
                self._set_normal(ic)
            self.emitted.add(shown)
            rows.append(
                _Row(
                    [display, f"LOINC {loinc}", _date(obs) or _date(stmt), shown],
                    [text_id, ot_id, None, None],
                )
            )
        return rows

    def _vital_value(self, loinc: str, unit: str | None, raw: str | None) -> tuple[str, str | None]:
        if loinc in _HEIGHT_CODES:
            if self.height_cm is None:
                self.height_cm = round(self.rng.uniform(155, 185), 1)
            if unit == "[in_i]":
                return _fmt(self.height_cm / 2.54, 1), unit
            if unit == "m":
                return _fmt(self.height_cm / 100, 2), unit
            return _fmt(self.height_cm, 1), "cm"
        if loinc in _WEIGHT_CODES:
            if self.weight_kg is None:
                self.weight_kg = round(self.rng.uniform(55, 95), 1)
            kg = self.weight_kg * self.rng.uniform(0.98, 1.02)
            if unit == "[lb_av]":
                return _fmt(kg * 2.2046, 1), unit
            if unit == "g":
                return _fmt(kg * 1000, 0), unit
            return _fmt(kg, 1), "kg"
        variants = VITALS.get(loinc)
        if variants:
            variant = next((v for v in variants if v[0] == unit), variants[0])
            return self._draw(variant[1], variant[2], variant[3]), variant[0]
        lab = LAB_BY_CODE.get(loinc)
        if lab:
            return self._draw(lab[3], lab[4], lab[5]), lab[2]
        return self._draw(1, 100, min(_decimals(raw), 2)), unit

    def _social_history(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        stmt = statement_of(entry)
        for obs in _observations(stmt):
            code_el = child(obs, "code")
            self._keep_code(code_el)
            loinc = attr(code_el, "code") or ""
            display = attr(code_el, "displayName") or self._emit("Social history")
            shown = self._social_value(obs, loinc)
            ot_id = self._set_original_text(code_el, display)
            text_id = self._set_text(obs, display)
            self.emitted.add(shown)
            rows.append(
                _Row(
                    [display, f"LOINC {loinc}", _date(obs) or _date(stmt), shown],
                    [text_id, ot_id, None, None],
                )
            )
        return rows

    def _social_value(self, obs: etree._Element, loinc: str) -> str:
        value = child(obs, "value")
        if value is None or attr(value, "nullFlavor") is not None:
            return ""
        templates = {attr(t, "root") for t in children(obs, "templateId")}
        text = text_of(value) or ""
        if (
            loinc == SMOKING_LOINC
            or _SMOKING_TEMPLATE in templates
            or attr(value, "code") in _SMOKING_VALUES
            or _SNOMED_TEXT.match(text)
        ):
            return self._never_smoker(value)
        kind = xsi_type(value)
        if attr(value, "value") is not None:
            if kind in {"BL", "TS"}:
                return value.get("value") or ""
            low, high, decimals = SOCIAL_VALUES.get(loinc, (0, 0, 0))
            number = self._draw(low, high, 0 if kind == "INT" else decimals)
            value.set("value", number)
            return f"{number} {attr(value, 'unit') or ''}".strip()
        if attr(value, "code") is not None:
            self._set_code(value, SNOMED, *UNKNOWN_VALUE)
            self._set_original_text(value, UNKNOWN_VALUE[1])
            return UNKNOWN_VALUE[1]
        if text:
            _set_plain_text(value, REMOVED)
            return REMOVED
        return ""

    def _never_smoker(self, value: etree._Element) -> str:
        code, display = NEVER_SMOKER
        if attr(value, "code") is not None or xsi_type(value) in _CODED_TYPES:
            self._set_code(value, SNOMED, code, display)
            self._set_original_text(value, display)
        else:
            current = text_of(value) or ""
            text = f"SNOMED-CT {code} {display}" if _SNOMED_TEXT.match(current) else display
            _set_plain_text(value, self._emit(text))
        return self._emit(display)

    def _encounters(self, entry: etree._Element) -> list[_Row]:
        rows: list[_Row] = []
        for enc in entry.iter(q("encounter")):
            code_el = child(enc, "code")
            self._keep_code(code_el)
            display = attr(code_el, "displayName") or self._emit("Encounter")
            system = attr(code_el, "codeSystem") or ""
            label = f"{_SYSTEM_NAMES.get(system, 'code')} {attr(code_el, 'code') or ''}".strip()
            ot_id = self._set_original_text(code_el, display)
            text_id = self._set_text(enc, display)
            rows.append(_Row([display, label, _date(enc), ""], [text_id, ot_id, None, None]))
        return rows

    # ---- narrative --------------------------------------------------------------------

    def _rebuild_narrative(self, section: Section, rows: list[_Row]) -> None:
        text_el = _ensure_text(section.element)
        _clear(text_el)
        if not rows:
            etree.SubElement(text_el, q("paragraph")).text = NARRATIVE_REMOVED
            return
        table = etree.SubElement(text_el, q("table"))
        head = etree.SubElement(etree.SubElement(table, q("thead")), q("tr"))
        for title in _HEADER:
            etree.SubElement(head, q("th")).text = title
        body = etree.SubElement(table, q("tbody"))
        for row in rows:
            tr = etree.SubElement(body, q("tr"))
            td = None
            for cell, rid in zip(row.cells, row.ids, strict=True):
                td = etree.SubElement(tr, q("td"))
                td.text = cell or None
                self.emitted.add(cell)
                if rid:
                    self._place(td, rid)
            for rid in row.extra:
                if rid not in self.placed_ids and td is not None:
                    self._place(etree.SubElement(td, q("content")), rid)
        etree.indent(text_el, space="  ")

    def _place(self, el: etree._Element, rid: str) -> None:
        if rid in self.placed_ids:
            return
        el.set("ID", rid)
        self.placed_ids.add(rid)

    # ---- residual check ---------------------------------------------------------------

    def _find_residuals(self, root: etree._Element) -> None:
        emitted = {e.lower() for e in self.emitted if e}
        tokens = [t for t in self.tokens if not any(t.lower() in e for e in emitted)]
        if not tokens:
            return
        alternatives = "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
        token_re = re.compile(f"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])", re.I)
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            for text in (el.text, el.tail):
                if not text:
                    continue
                for m in token_re.finditer(text):
                    self.report.residual_findings.append(f"{m.group(0)!r} at {_path(el)}")


_HANDLERS = {
    "48765-2": "_allergies",
    "10160-0": "_medications",
    "11450-4": "_problems",
    "47519-4": "_procedures",
    "46240-8": "_encounters",
    "8716-3": "_vitals",
    "30954-2": "_results",
    "11369-6": "_immunizations",
    "29762-2": "_social_history",
}


def _is_generic(el: etree._Element) -> bool:
    """True for codes that describe the record (status, kinds, categories), not the patient."""
    code = attr(el, "code")
    if code is None or code in GENERIC_CODES or local_name(el) in _GENERIC_LOCALS:
        return True
    system = attr(el, "codeSystem")
    if system is None:
        return local_name(el) not in {"code", "value", "translation"}
    if system == CVX:
        return False
    return system in _GENERIC_SYSTEMS or system.startswith(_GENERIC_SYSTEM_PREFIXES)


def _content_name(name_el: etree._Element) -> bool:
    parent = name_el.getparent()
    if parent is None or not isinstance(parent.tag, str):
        return False
    local = local_name(parent)
    if local == "playingEntity":
        return attr(parent, "classCode") == "MMAT"
    return local in _CONTENT_NAME_PARENTS


def _observations(stmt: etree._Element | None) -> list[etree._Element]:
    """The observation itself, or an organizer's component observations."""
    if stmt is None:
        return []
    if local_name(stmt) == "observation":
        return [stmt]
    if local_name(stmt) == "organizer":
        return [o for c in children(stmt, "component") for o in children(c, "observation")]
    return []


def _refs(entry: etree._Element) -> list[str]:
    """Narrative IDs referenced anywhere in an entry, in document order, without repeats."""
    out: list[str] = []
    for ref in entry.iter(q("reference")):
        rid = _ref_id(ref)
        if rid and rid not in out:
            out.append(rid)
    return out


def _ref_id(ref: etree._Element | None) -> str | None:
    value = attr(ref, "value")
    if not value:
        return None
    return value[1:] if value.startswith("#") else value


def _effective_times(root: etree._Element) -> list[str]:
    """Every TS value on an effectiveTime or one of its bounds."""
    out: list[str] = []
    for et in root.iter(q("effectiveTime")):
        for el in (et, *et):
            if isinstance(el.tag, str) and (raw := attr(el, "value")):
                out.append(raw)
    return out


def _year(raw: str) -> int | None:
    return int(raw[:4]) if len(raw) >= 8 and raw[:8].isdigit() else None


def _date(el: etree._Element | None) -> str:
    """``YYYY-MM-DD`` of an element's effectiveTime (point, low or high), or empty."""
    if el is None:
        return ""
    for et in children(el, "effectiveTime"):
        if xsi_type(et) in _TIMING_TYPES:
            continue
        for candidate in (et, child(et, "low"), child(et, "high"), child(et, "center")):
            raw = attr(candidate, "value")
            if raw and raw[:8].isdigit():
                return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def _decimals(raw: str | None) -> int:
    if not raw or "." not in raw:
        return 0
    return len(re.match(r"\d*", raw.split(".", 1)[1]).group(0))


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _clear(el: etree._Element) -> None:
    for c in list(el):
        el.remove(c)
    el.text = None


def _set_plain_text(el: etree._Element, text: str) -> None:
    _clear(el)
    el.text = text


def _ensure_text(section_el: etree._Element) -> etree._Element:
    text_el = child(section_el, "text")
    if text_el is not None:
        return text_el
    text_el = etree.Element(q("text"))
    entries = children(section_el, "entry")
    if entries:
        section_el.insert(section_el.index(entries[0]), text_el)
    else:
        section_el.append(text_el)
    return text_el


def _path(el: etree._Element) -> str:
    """XPath-like location using local names and sibling positions."""
    parts: list[str] = []
    node: etree._Element | None = el
    while node is not None and isinstance(node.tag, str):
        parent = node.getparent()
        name = local_name(node)
        if parent is not None:
            same = [c for c in parent if isinstance(c.tag, str) and c.tag == node.tag]
            if len(same) > 1:
                name += f"[{same.index(node) + 1}]"
        parts.append(name)
        node = parent
    return "/" + "/".join(reversed(parts))
