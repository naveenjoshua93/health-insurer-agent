"""Generates synthetic claim-document images for the reimbursement OCR demo (Moment 2).

Matches CL-1003 (Anil Kumar, PRS Hospital, Thiruvananthapuram) so the Tester's Crib
Sheet script works out of the box: upload hospital_bill.png + prescription.png first,
the flow should report discharge_summary and pan_card still missing (matching
claims.json's pending_documents for CL-1003); uploading those two completes the file.

Run once: python scripts/generate_sample_documents.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent.parent / "src" / "data" / "documents"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 900, 1200
MARGIN = 60
INDIC_FONT_PATH = "C:/Windows/Fonts/Nirmala.ttc"


def _font(size, indic=False):
    path = INDIC_FONT_PATH if indic else "C:/Windows/Fonts/arial.ttf"
    return ImageFont.truetype(path, size)


def _render(filename, title, lines, indic=False):
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    title_font = _font(38, indic)
    body_font = _font(26, indic)

    draw.rectangle([(0, 0), (WIDTH, 110)], fill="#1d3557")
    draw.text((MARGIN, 35), title, font=title_font, fill="white")

    y = 150
    for line in lines:
        if line == "":
            y += 18
            continue
        draw.text((MARGIN, y), line, font=body_font, fill="#1d1d1f")
        y += 42

    draw.rectangle([(0, 0), (WIDTH - 1, HEIGHT - 1)], outline="#d1d5db", width=2)
    img.save(OUT_DIR / filename)
    print(f"wrote {filename}")


_render(
    "hospital_bill.png",
    "PRS HOSPITAL, THIRUVANANTHAPURAM - FINAL BILL",
    [
        "Patient Name: Anil Kumar",
        "Policy No: SMP-HL-500125",
        "Claim ID: CL-1003",
        "Admission Date: 03-Jun-2026    Discharge Date: 07-Jun-2026",
        "",
        "Itemised Charges:",
        "  Room Rent (4 days x Rs 3,500)              Rs 14,000",
        "  Surgeon & Anaesthetist Fees                Rs 22,000",
        "  Operation Theatre Charges                  Rs 8,500",
        "  Investigations & Diagnostics                Rs 9,200",
        "  Pharmacy & Consumables                     Rs 6,300",
        "  Nursing & Attendant Charges                 Rs 2,000",
        "",
        "Total Amount Payable:                        Rs 62,000",
        "",
        "Payment Received: Cash/Card - Paid in full by patient",
        "Authorised Signatory: Billing Dept, PRS Hospital",
    ],
)

_render(
    "pharmacy_bill.png",
    "PRS HOSPITAL PHARMACY - CASH MEMO",
    [
        "Patient Name: Anil Kumar",
        "Claim ID: CL-1003",
        "Bill Date: 07-Jun-2026",
        "",
        "Items:",
        "  Tab. Augmentin 625mg x 10                   Rs 420",
        "  Inj. Pantoprazole 40mg x 5                  Rs 260",
        "  IV Fluids - Normal Saline x 6                Rs 540",
        "  Surgical Gauze & Dressing Kit                Rs 380",
        "  Syringes & Cannula                          Rs 210",
        "",
        "Total:                                       Rs 1,810",
        "",
        "GST Reg No: 32AACPK1234R1ZP",
    ],
)

_render(
    "discharge_summary.png",
    "PRS HOSPITAL - DISCHARGE SUMMARY",
    [
        "Patient Name: Anil Kumar        Age/Sex: 46 / Male",
        "Policy No: SMP-HL-500125        Claim ID: CL-1003",
        "Admission Date: 03-Jun-2026     Discharge Date: 07-Jun-2026",
        "",
        "Diagnosis: Acute Appendicitis",
        "Procedure Performed: Laparoscopic Appendectomy",
        "",
        "Course in Hospital:",
        "  Patient was admitted with severe right lower abdominal pain.",
        "  Underwent laparoscopic appendectomy on 04-Jun-2026 under general",
        "  anaesthesia. Post-operative recovery was uneventful.",
        "",
        "Condition at Discharge: Stable, afebrile, wound healing well.",
        "Advice on Discharge: Oral antibiotics for 5 days, review after 1 week,",
        "  avoid heavy lifting for 2 weeks.",
        "",
        "Consultant Surgeon: Dr. K. Sreekumar, MS (General Surgery)",
    ],
)

_render(
    "pan_card.png",
    "INCOME TAX DEPARTMENT - GOVT OF INDIA",
    [
        "Permanent Account Number Card",
        "",
        "Name: ANIL KUMAR",
        "Father's Name: RAGHAVAN NAIR",
        "Date of Birth: 12/08/1980",
        "",
        "Permanent Account Number:",
        "  AAKPK4321Q",
        "",
        "(Specimen for demo purposes only - fictional data)",
    ],
)

# Prescription rendered in Malayalam (Thiruvananthapuram hospital) to show Indic OCR,
# per the data pack's note that some sample documents should use regional script.
_render(
    "prescription.png",
    "PRS ഹോസ്പിറ്റൽ - ഡോക്ടറുടെ കുറിപ്പടി",
    [
        "രോഗിയുടെ പേര്: അനിൽ കുമാർ",
        "ക്ലെയിം ഐഡി: CL-1003",
        "തീയതി: 07-06-2026",
        "",
        "രോഗനിർണയം: അക്യൂട്ട് അപ്പെൻഡിസൈറ്റിസ് (ശസ്ത്രക്രിയാനന്തരം)",
        "",
        "മരുന്നുകൾ:",
        "  1. ടാബ്. അമോക്സിക്ലാവ് 625mg - ദിവസം 2 നേരം x 5 ദിവസം",
        "  2. ടാബ്. പാന്റോപ്രാസോൾ 40mg - രാവിലെ ഒരു നേരം x 5 ദിവസം",
        "  3. ടാബ്. പാരാസെറ്റമോൾ 650mg - ആവശ്യമെങ്കിൽ",
        "",
        "ഡോ. കെ. ശ്രീകുമാർ, എം.എസ്. (ജനറൽ സർജറി)",
    ],
    indic=True,
)

print("done")
