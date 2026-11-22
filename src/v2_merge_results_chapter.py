"""
Merge the v2 results chapter into the report as Chapter 4.

Input:
    ../ICT431_202308647_EltonChiwala_v2.docx
    docs/RESULTS_CHAPTER.docx

Output:
    ../ICT431_202308647_EltonChiwala_final.docx

Existing Chapter 4 (Project Management) becomes Chapter 5, and Chapter 5
(Conclusion) becomes Chapter 6. The results chapter becomes Chapter 4.
Table/figure/section references in the existing chapters are shifted with it.
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docxcompose.composer import Composer

BASE = Path(__file__).resolve().parents[2]
SRC = BASE / "ICT431_202308647_EltonChiwala_v2.docx"
RESULTS = BASE / "prototype" / "docs" / "RESULTS_CHAPTER.docx"
OUT = BASE / "ICT431_202308647_EltonChiwala_final.docx"


def shift_refs(text: str) -> str:
    """Shift Section/Table/Figure references from 4.x/5.x to 5.x/6.x."""
    # Reverse order so 4 -> 5 does not immediately become 6.
    text = re.sub(r"\bSection 5\.", "Section 6.", text)
    text = re.sub(r"\bSection 4\.", "Section 5.", text)
    text = re.sub(r"\bTable 5\.", "Table 6.", text)
    text = re.sub(r"\bTable 4\.", "Table 5.", text)
    text = re.sub(r"\bFigure 5\.", "Figure 6.", text)
    text = re.sub(r"\bFigure 4\.", "Figure 5.", text)
    return text


def shift_heading(text: str) -> str:
    if text.startswith("CHAPTER 5"):
        return text.replace("CHAPTER 5", "CHAPTER 6", 1)
    if text.startswith("CHAPTER 4"):
        return text.replace("CHAPTER 4", "CHAPTER 5", 1)
    if re.match(r"^5\.", text):
        return "6." + text[2:]
    if re.match(r"^4\.", text):
        return "5." + text[2:]
    return text


def replace_in_runs(paragraph, func) -> bool:
    changed = False
    for run in paragraph.runs:
        new = func(run.text)
        if new != run.text:
            run.text = new
            changed = True
    return changed


def main() -> None:
    doc = Document(SRC)

    # ---- renumber existing headings, TOC entries and references -----------
    for p in doc.paragraphs:
        style = p.style.name
        if style.startswith("Heading"):
            new = shift_heading(p.text)
            if new != p.text:
                p.text = new
        elif style.lower().startswith("toc"):
            # TOC entries contain tabs/page numbers; modify runs to preserve them.
            replace_in_runs(p, shift_heading)
            replace_in_runs(p, shift_refs)
        else:
            replace_in_runs(p, shift_refs)

    # ---- append the results chapter at the end ---------------------------
    composer = Composer(doc)
    composer.append(Document(RESULTS))
    doc = composer.doc

    # The appended chapter is the last Heading 1 named "Results and Discussion".
    results_heading = None
    for p in reversed(doc.paragraphs):
        if p.style.name.startswith("Heading 1") and p.text.strip() == "Results and Discussion":
            results_heading = p
            break
    if results_heading is None:
        raise RuntimeError("could not find appended Results and Discussion heading")

    results_heading.text = "CHAPTER 4 \u2013 RESULTS AND DISCUSSION"
    results_heading.paragraph_format.page_break_before = True

    # Target: the renumbered Chapter 5 (Project Management).
    target = None
    for p in doc.paragraphs:
        t = p.text.upper()
        if p.style.name.startswith("Heading 1") and "CHAPTER 5" in t and "PROJECT MANAGEMENT" in t:
            target = p
            break
    if target is None:
        raise RuntimeError("could not find CHAPTER 5 PROJECT MANAGEMENT heading")
    target.paragraph_format.page_break_before = True

    # Move everything from the appended results heading up to (not including)
    # the final sectPr to just before Chapter 5.
    body = doc.element.body
    block = []
    el = results_heading._p
    while el is not None:
        if el.tag == qn("w:sectPr"):
            break
        block.append(el)
        el = el.getnext()

    if not block:
        raise RuntimeError("results chapter block is empty")

    for el in block:
        body.remove(el)
    for el in block:
        target._p.addprevious(el)

    # Add Chapter 4 entries to the static table of contents. Page numbers are
    # placeholders because the inserted chapter shifts every later page; update
    # the TOC/page numbers in Word after merging.
    toc_target = None
    for p in doc.paragraphs:
        if p.style.name.lower().startswith("toc 1") and p.text.strip().startswith("CHAPTER 5"):
            toc_target = p
            break
    if toc_target is not None:
        entries = [
            ("CHAPTER 4 \u2013 RESULTS AND DISCUSSION", "toc 1"),
            ("4.1 Evaluation protocol", "toc 2"),
            ("4.2 Overall performance", "toc 2"),
            ("4.3 Per-site behaviour", "toc 2"),
            ("4.4 Peak-demand performance", "toc 2"),
            ("4.5 Ablations: readiness and weather", "toc 2"),
            ("4.6 Stage 2 selection: HGB versus LSTM", "toc 2"),
            ("4.7 Standalone LSTM baseline", "toc 2"),
            ("4.8 Discussion", "toc 2"),
            ("4.9 Limitations", "toc 2"),
            ("4.10 Summary", "toc 2"),
        ]
        for text, style_name in entries:
            toc_target.insert_paragraph_before(f"{text}\tTBD", style=style_name)

    # Add the new figure/table entries to the static lists of figures/tables.
    fig_target = next(
        (p for p in doc.paragraphs
         if p.style.name == "List Entry" and p.text.strip().startswith("Figure 5.1")),
        None,
    )
    if fig_target is not None:
        for text in [
            "Figure 4.1: Mean RMSE by forecast horizon",
            "Figure 4.2: Mean MAE by forecast horizon",
            "Figure 4.3: Hybrid minus XGB RMSE heatmap",
            "Figure 4.4: XGBoost versus selected hybrid by site",
            "Figure 4.5: Top-decile peak bias by horizon",
            "Figure 4.6: Ablation of readiness and weather features",
            "Figure 4.7: Validation-selected Stage 2",
        ]:
            fig_target.insert_paragraph_before(f"{text}\tTBD", style="List Entry")

    table_target = next(
        (p for p in doc.paragraphs
         if p.style.name == "List Entry" and p.text.strip().startswith("Table 5.1")),
        None,
    )
    if table_target is not None:
        for text in [
            "Table 4.1: Chronological splits",
            "Table 4.2: Mean RMSE across the six sites",
            "Table 4.3: Mean MAE across the six sites",
            "Table 4.4: Selected hybrid minus XGB RMSE",
            "Table 4.5: Top-decile peak bias",
            "Table 4.6: Mean RMSE by ablation",
            "Table 4.7: Validation-selected Stage 2 counts",
        ]:
            table_target.insert_paragraph_before(f"{text}\tTBD", style="List Entry")

    doc.save(OUT)
    print(f"wrote {OUT}")
    print(f"moved {len(block)} XML elements before Chapter 5")


if __name__ == "__main__":
    main()
