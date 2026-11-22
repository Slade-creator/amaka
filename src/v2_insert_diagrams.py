"""Insert the five Mermaid-derived figures into the final report's Chapter 3."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

BASE = Path(r"C:\Users\TMB COMPUTERS\Documents\school\4th year\final year project")
DOC = BASE / "ICT431_202308647_EltonChiwala_final.docx"
FIG = BASE / "prototype" / "docs" / "figures"

FIGURES = [
    ("fig_3_2_data_prep.png", "Figure 3.2 - Data preparation and feature engineering pipeline.", 6.0,
     "Figure 3.2: Data preparation and feature engineering pipeline"),
    ("fig_3_3_grid_logic.png", "Figure 3.3 - Grid supply and load-shedding logic for security-wing sites.", 6.0,
     "Figure 3.3: Grid supply and load-shedding logic"),
    ("fig_3_4_telemetry.png", "Figure 3.4 - Internal telemetry disruption handling.", 5.5,
     "Figure 3.4: Internal telemetry disruption handling"),
    ("fig_3_5_hybrid_model.png", "Figure 3.5 - Hybrid model training and evaluation.", 6.0,
     "Figure 3.5: Hybrid model training and evaluation"),
    ("fig_3_6_timeline.png", "Figure 3.6 - Chronological evaluation protocol.", 5.8,
     "Figure 3.6: Chronological evaluation protocol"),
]


def find_heading(doc: Document, fragment: str):
    for p in doc.paragraphs:
        if p.style.name.startswith("Heading") and fragment in p.text:
            return p
    raise RuntimeError(f"heading not found: {fragment}")


def insert_figure(doc: Document, before, image: str, caption: str, width: float, list_text: str) -> None:
    p = before.insert_paragraph_before()
    run = p.add_run()
    run.add_picture(str(FIG / image), width=Inches(width))
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    cap = before.insert_paragraph_before(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cap.runs:
        cap.runs[0].italic = True
        cap.runs[0].font.size = Pt(9)

    # Add to the List of Figures before the first pre-existing Figure 4.1 entry.
    list_marker = None
    for q in doc.paragraphs:
        if q.style.name == "List Entry" and q.text.strip().startswith("Figure 4.1"):
            list_marker = q
            break
    if list_marker is not None:
        list_marker.insert_paragraph_before(f"{list_text}\tTBD", style="List Entry")


def main() -> None:
    doc = Document(DOC)

    before_322 = find_heading(doc, "3.2.2 Hybrid AI Model Development")
    for image, caption, width, list_text in FIGURES[:3]:
        insert_figure(doc, before_322, image, caption, width, list_text)

    before_323 = find_heading(doc, "3.2.3 Backend API")
    insert_figure(doc, before_323, *FIGURES[3])

    before_33 = find_heading(doc, "3.3 Justification of Selected Methodology")
    insert_figure(doc, before_33, *FIGURES[4])

    doc.save(DOC)
    print(f"inserted {len(FIGURES)} figures into {DOC}")


if __name__ == "__main__":
    main()
