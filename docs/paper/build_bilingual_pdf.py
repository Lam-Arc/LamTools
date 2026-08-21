"""Build one Chinese-first bilingual LamTools paper PDF."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
ZH_SOURCE = ROOT / "docs" / "paper" / "lamtools-technical-paper-zh.md"
EN_SOURCE = ROOT / "docs" / "paper" / "lamtools-technical-paper.md"
OUTPUT = ROOT / "output" / "pdf" / "lamtools-technical-paper-bilingual-v0.2.6.pdf"
FONT_REGULAR = r"C:\Windows\Fonts\Deng.ttf"
FONT_BOLD = r"C:\Windows\Fonts\Dengb.ttf"


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Deng", FONT_REGULAR))
    pdfmetrics.registerFont(TTFont("DengBold", FONT_BOLD))


def clean_text(value: str) -> str:
    value = value.replace("\\*", "")
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = value.replace("\\", "")
    value = value.replace("–", "-").replace("—", "-").replace("‑", "-")
    value = value.replace("“", '"').replace("”", '"').replace("’", "'")
    return value.strip()


def para_text(value: str) -> str:
    return escape(clean_text(value)).replace("\n", "<br/>")


def split_table_row(line: str) -> list[str]:
    text = line.strip().strip("|")
    return [clean_text(cell.strip()) for cell in text.split("|")]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def parse_table(lines: list[str], start: int, style: ParagraphStyle, header_style: ParagraphStyle):
    block: list[str] = []
    index = start
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        block.append(lines[index])
        index += 1
    if len(block) < 2:
        return [], index
    rows = [split_table_row(row) for row in block if not is_table_separator(row)]
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(rows):
        cell_style = header_style if row_index == 0 else style
        data.append([Paragraph(escape(cell), cell_style) for cell in row])
    total_width = 168 * mm
    table = Table(data, colWidths=[total_width / width] * width, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C4CF")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F9")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [table, Spacer(1, 6)], index


def styles_for(language: str) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    chinese = language == "zh"
    regular = "Deng" if chinese else "Helvetica"
    bold = "DengBold" if chinese else "Helvetica-Bold"
    wrap = "CJK" if chinese else None
    return {
        "title": ParagraphStyle(
            f"{language}Title", parent=sample["Title"], fontName=bold,
            fontSize=21 if chinese else 22, leading=27, textColor=colors.HexColor("#17324D"),
            alignment=TA_CENTER, spaceAfter=10, wordWrap=wrap,
        ),
        "authors": ParagraphStyle(
            f"{language}Authors", parent=sample["Normal"], fontName=regular,
            fontSize=11, leading=15, alignment=TA_CENTER,
            textColor=colors.HexColor("#34495E"), spaceAfter=5, wordWrap=wrap,
        ),
        "meta": ParagraphStyle(
            f"{language}Meta", parent=sample["Normal"], fontName=regular,
            fontSize=8.5, leading=12, alignment=TA_CENTER,
            textColor=colors.HexColor("#64748B"), spaceAfter=16, wordWrap=wrap,
        ),
        "h1": ParagraphStyle(
            f"{language}H1", parent=sample["Heading1"], fontName=bold,
            fontSize=14, leading=18, textColor=colors.HexColor("#17324D"),
            spaceBefore=13, spaceAfter=6, keepWithNext=True, wordWrap=wrap,
        ),
        "body": ParagraphStyle(
            f"{language}Body", parent=sample["BodyText"], fontName=regular,
            fontSize=9.1, leading=12.5, alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#1F2933"), spaceAfter=6, wordWrap=wrap,
        ),
        "bullet": ParagraphStyle(
            f"{language}Bullet", parent=sample["BodyText"], fontName=regular,
            fontSize=9.0, leading=12, leftIndent=13, firstLineIndent=-8,
            textColor=colors.HexColor("#1F2933"), spaceAfter=3, wordWrap=wrap,
        ),
        "code": ParagraphStyle(
            f"{language}Code", parent=sample["Code"], fontName="Courier",
            fontSize=7.2, leading=9, leftIndent=8, rightIndent=8,
            backColor=colors.HexColor("#F3F6F8"), borderColor=colors.HexColor("#D6DEE5"),
            borderWidth=0.4, borderPadding=6, spaceBefore=3, spaceAfter=8,
        ),
        "table_header": ParagraphStyle(
            f"{language}TableHeader", parent=sample["Normal"], fontName=bold,
            fontSize=6.6, leading=8, textColor=colors.white, wordWrap=wrap,
        ),
        "table_cell": ParagraphStyle(
            f"{language}TableCell", parent=sample["Normal"], fontName=regular,
            fontSize=6.4, leading=7.7, textColor=colors.HexColor("#1F2933"), wordWrap=wrap,
        ),
        "caption": ParagraphStyle(
            f"{language}Caption", parent=sample["BodyText"], fontName=regular,
            fontSize=7.5, leading=9.5, alignment=TA_CENTER,
            textColor=colors.HexColor("#64748B"), spaceBefore=3, spaceAfter=9, wordWrap=wrap,
        ),
        "references": ParagraphStyle(
            f"{language}References", parent=sample["BodyText"], fontName=regular,
            fontSize=8.2, leading=10.5, leftIndent=10, firstLineIndent=-10,
            textColor=colors.HexColor("#1F2933"), spaceAfter=5, wordWrap=wrap,
        ),
    }


def build_section(source: Path, language: str) -> list:
    styles = styles_for(language)
    lines = source.read_text(encoding="utf-8").splitlines()
    story: list = []
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []
    image_root = source.parent

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(item.strip() for item in paragraph if item.strip())
            if text:
                story.append(Paragraph(para_text(text), styles["body"]))
            paragraph.clear()

    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if stripped == "```":
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"]))
                code_lines.clear()
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(raw.rstrip())
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            table_story, next_index = parse_table(lines, index, styles["table_cell"], styles["table_header"])
            story.extend(table_story)
            index = next_index
            continue
        if stripped.startswith("!["):
            flush_paragraph()
            match = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
            if match:
                caption, relative_path = match.groups()
                image = Image(str(image_root / relative_path))
                max_width = 168 * mm
                scale = min(1.0, max_width / image.imageWidth)
                image.drawWidth = image.imageWidth * scale
                image.drawHeight = image.imageHeight * scale
                story.append(image)
                story.append(Paragraph(escape(caption), styles["caption"]))
            index += 1
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            title = clean_text(stripped[2:])
            story.append(Paragraph(escape(title), styles["title"]))
            if language == "zh":
                author_line = "张玉霖 与 张一明 - 共同第一作者<br/>独立研究员"
                meta_line = "中文主版本 / Chinese-primary version - LamTools v0.2.6 - 审计 2026-08-20；全量复核 2026-08-21<br/>Software DOI：10.5281/zenodo.22039646"
            else:
                author_line = "Yulin Zhang and Yiming Zhang - Equal contribution<br/>Independent Researcher"
                meta_line = "English version - LamTools v0.2.6 - audited 20 August 2026; full rerun 21 August 2026<br/>Software DOI: 10.5281/zenodo.22039646"
            story.append(Paragraph(author_line, styles["authors"]))
            story.append(Paragraph(meta_line, styles["meta"]))
            index += 1
            continue
        if stripped.startswith("**Yulin Zhang") or stripped.startswith("**张玉霖") or stripped.startswith("\\*Equal contribution") or stripped.startswith("\\*共同第一作者"):
            index += 1
            continue
        if stripped.startswith("## ") or stripped.startswith("### "):
            flush_paragraph()
            marker = 3 if stripped.startswith("### ") else 2
            story.append(Paragraph(escape(clean_text(stripped[marker:])), styles["h1"]))
            index += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            story.append(Paragraph("&#8226; " + para_text(stripped[2:]), styles["bullet"]))
            index += 1
            continue
        if re.match(r"^\d+\. ", stripped):
            flush_paragraph()
            story.append(Paragraph(para_text(stripped), styles["bullet"]))
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    return story


def decorate_page(canvas, document) -> None:
    canvas.saveState()
    page = canvas.getPageNumber()
    width, height = A4
    if page > 1:
        canvas.setStrokeColor(colors.HexColor("#D8E0E7"))
        canvas.setLineWidth(0.45)
        canvas.line(21 * mm, height - 15 * mm, width - 21 * mm, height - 15 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(21 * mm, height - 11.5 * mm, "LamTools Bilingual Technical Paper")
        canvas.drawRightString(width - 21 * mm, height - 11.5 * mm, "v0.2.6")
    canvas.setStrokeColor(colors.HexColor("#D8E0E7"))
    canvas.setLineWidth(0.45)
    canvas.line(21 * mm, 15 * mm, width - 21 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawCentredString(width / 2, 10.5 * mm, str(page))
    canvas.restoreState()


def main() -> None:
    register_fonts()
    story = build_section(ZH_SOURCE, "zh")
    story.append(PageBreak())
    story.extend(build_section(EN_SOURCE, "en"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=21 * mm, rightMargin=21 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title="LamTools：具备能力感知委派机制的本地优先 Agent 运行时 / LamTools: A Local-First Agent Runtime with Capability-Aware Delegation",
        author="Yulin Zhang; Yiming Zhang",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="paper", frames=[frame], onPage=decorate_page)])
    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    main()
