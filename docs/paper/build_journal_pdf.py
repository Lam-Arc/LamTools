"""Build the Chinese-first bilingual LamTools paper in a journal-style layout.

This is an original two-column technical-paper layout inspired by common
research conventions. It does not reproduce a publisher's proprietary template.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle,
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


def rich_text(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    return escape(value)


def split_table_row(line: str) -> list[str]:
    text = line.strip().strip("|")
    return [clean_text(cell.strip()) for cell in text.split("|")]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def make_styles(language: str) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    chinese = language == "zh"
    body_font = "Deng" if chinese else "Times-Roman"
    bold_font = "DengBold" if chinese else "Helvetica-Bold"
    sans_font = "Deng" if chinese else "Helvetica"
    wrap = "CJK" if chinese else None
    return {
        "title": ParagraphStyle(f"{language}Title", parent=sample["Title"], fontName=bold_font,
            fontSize=21 if chinese else 22, leading=25 if chinese else 26,
            alignment=TA_CENTER, textColor=colors.HexColor("#17324D"), spaceAfter=8, wordWrap=wrap),
        "authors": ParagraphStyle(f"{language}Authors", parent=sample["Normal"], fontName=sans_font,
            fontSize=10.5, leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#34495E"),
            spaceAfter=4, wordWrap=wrap),
        "meta": ParagraphStyle(f"{language}Meta", parent=sample["Normal"], fontName=sans_font,
            fontSize=7.8, leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#64748B"),
            spaceAfter=11, wordWrap=wrap),
        "h1": ParagraphStyle(f"{language}H1", parent=sample["Heading1"], fontName=bold_font,
            fontSize=12.2, leading=14.5, textColor=colors.HexColor("#17324D"), spaceBefore=8,
            spaceAfter=4, keepWithNext=True, wordWrap=wrap),
        "h2": ParagraphStyle(f"{language}H2", parent=sample["Heading2"], fontName=bold_font,
            fontSize=10.2, leading=12, textColor=colors.HexColor("#244A68"), spaceBefore=6,
            spaceAfter=3, keepWithNext=True, wordWrap=wrap),
        "body": ParagraphStyle(f"{language}Body", parent=sample["BodyText"], fontName=body_font,
            fontSize=8.65 if chinese else 8.7, leading=11.1 if chinese else 10.8,
            alignment=TA_JUSTIFY if chinese else TA_LEFT, textColor=colors.HexColor("#1F2933"), spaceAfter=4.5, wordWrap=wrap),
        "cover_body": ParagraphStyle(f"{language}CoverBody", parent=sample["BodyText"], fontName=body_font,
            fontSize=8.85 if chinese else 9.0, leading=11.8 if chinese else 11.6,
            alignment=TA_JUSTIFY if chinese else TA_LEFT, textColor=colors.HexColor("#1F2933"), spaceAfter=5, wordWrap=wrap),
        "bullet": ParagraphStyle(f"{language}Bullet", parent=sample["BodyText"], fontName=body_font,
            fontSize=8.5, leading=10.8, leftIndent=10, firstLineIndent=-7,
            textColor=colors.HexColor("#1F2933"), spaceAfter=2.5, wordWrap=wrap),
        "caption": ParagraphStyle(f"{language}Caption", parent=sample["BodyText"], fontName=sans_font,
            fontSize=6.8, leading=8.3, alignment=TA_JUSTIFY if chinese else TA_LEFT, textColor=colors.HexColor("#536779"),
            spaceBefore=2, spaceAfter=6, wordWrap=wrap),
        "table_header": ParagraphStyle(f"{language}TableHeader", parent=sample["Normal"], fontName=bold_font,
            fontSize=5.8, leading=7, textColor=colors.white, wordWrap=wrap),
        "table_cell": ParagraphStyle(f"{language}TableCell", parent=sample["Normal"], fontName=body_font,
            fontSize=5.65 if chinese else 5.6, leading=6.7, textColor=colors.HexColor("#1F2933"), wordWrap=wrap),
        "references": ParagraphStyle(f"{language}References", parent=sample["BodyText"], fontName=body_font,
            fontSize=6.7, leading=8.0, leftIndent=7, firstLineIndent=-7,
            textColor=colors.HexColor("#1F2933"), spaceAfter=3, wordWrap=wrap),
    }


def table_flowable(lines: list[str], styles: dict[str, ParagraphStyle], available_width: float):
    rows = [split_table_row(line) for line in lines if not is_table_separator(line)]
    if len(rows) < 2:
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(rows):
        style = styles["table_header"] if row_index == 0 else styles["table_cell"]
        data.append([Paragraph(escape(cell), style) for cell in row])
    table = Table(data, colWidths=[available_width / width] * width, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B8C4CF")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F9")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def parse_source(source: Path, language: str, column_width: float):
    styles = make_styles(language)
    lines = source.read_text(encoding="utf-8").splitlines()
    cover, body = [], []
    current = cover
    paragraph, code_lines = [], []
    in_code = False
    in_references = False
    image_root = source.parent

    def flush() -> None:
        if paragraph:
            text = " ".join(item.strip() for item in paragraph if item.strip())
            if text:
                style = styles["references"] if in_references else (styles["cover_body"] if current is cover else styles["body"])
                current.append(Paragraph(rich_text(text), style))
            paragraph.clear()

    def heading(text: str, level: int) -> None:
        nonlocal in_references
        flush()
        title = clean_text(text)
        current.append(Paragraph(escape(title), styles["h1"] if level == 1 else styles["h2"]))
        if level == 1:
            in_references = "参考文献" in title or "References" in title

    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "```":
            flush()
            if in_code:
                current.append(Preformatted("\n".join(code_lines), styles["body"]))
                code_lines.clear()
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(lines[index].rstrip())
            index += 1
            continue
        if not stripped:
            flush(); index += 1; continue
        if stripped.startswith("|"):
            flush(); table_lines = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                table_lines.append(lines[index]); index += 1
            table = table_flowable(table_lines, styles, column_width)
            if table is not None: current.extend([table, Spacer(1, 4)])
            continue
        if stripped.startswith("!["):
            flush(); match = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
            if match:
                caption, relative = match.groups()
                image = Image(str(image_root / relative))
                scale = min(1.0, column_width / image.imageWidth)
                image.drawWidth = image.imageWidth * scale; image.drawHeight = image.imageHeight * scale
                current.extend([image, Paragraph(rich_text(caption), styles["caption"])])
            index += 1; continue
        if stripped.startswith("# "):
            flush(); current.append(Paragraph(escape(clean_text(stripped[2:])), styles["title"]))
            if language == "zh":
                author = "张玉霖 与 张一明 - 共同第一作者<br/>独立研究员"
                meta = "中文主版本 / Chinese-primary version - Technical Paper / Preprint - LamTools v0.2.6 - 审计 2026-08-20；全量复核 2026-08-21<br/>Software DOI：10.5281/zenodo.22039646<br/>Paper DOI：10.5281/zenodo.22040870"
            else:
                author = "Yulin Zhang and Yiming Zhang - Equal contribution<br/>Independent Researcher"
                meta = "English version - Technical Paper / Preprint - LamTools v0.2.6 - audited 20 August 2026; full rerun 21 August 2026<br/>Software DOI: 10.5281/zenodo.22039646<br/>Paper DOI: 10.5281/zenodo.22040870"
            current.extend([Paragraph(author, styles["authors"]), Paragraph(meta, styles["meta"])])
            index += 1; continue
        if (stripped.startswith("**") or stripped.startswith("\\*")) and (
            "共同第一作者" in stripped or "Equal contribution" in stripped or "作者顺序" in stripped or "Author order" in stripped
            or "张玉霖" in stripped or "Yulin Zhang" in stripped
        ):
            index += 1; continue
        if stripped.startswith("## "):
            title = stripped[3:]
            if re.match(r"^1[.、]", title) and current is cover:
                flush(); current = body
            if ("参考文献" in title or "References" in title) and current is body:
                flush()
                heading(title, 1); index += 1; continue
            heading(title, 1); index += 1; continue
        if stripped.startswith("### "):
            heading(stripped[4:], 2); index += 1; continue
        if stripped.startswith("- "):
            flush(); current.append(Paragraph("&#8226; " + rich_text(stripped[2:]), styles["bullet"])); index += 1; continue
        if re.match(r"^\d+[.、] ", stripped):
            flush(); current.append(Paragraph(rich_text(stripped), styles["bullet"])); index += 1; continue
        paragraph.append(stripped); index += 1
    flush()
    return cover, body


def decorate_page(canvas, document) -> None:
    canvas.saveState(); page = canvas.getPageNumber(); width, height = A4
    canvas.setStrokeColor(colors.HexColor("#D8E0E7")); canvas.setLineWidth(0.45)
    canvas.line(21 * mm, 15 * mm, width - 21 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.2); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawCentredString(width / 2, 10.5 * mm, str(page))
    if page > 1:
        canvas.line(21 * mm, height - 15 * mm, width - 21 * mm, height - 15 * mm)
        canvas.drawString(21 * mm, height - 11.5 * mm, "LamTools | Bilingual Technical Paper")
        canvas.drawRightString(width - 21 * mm, height - 11.5 * mm, "v0.2.6")
    canvas.restoreState()


def main() -> None:
    register_fonts()
    margin_x, margin_y = 21 * mm, 20 * mm
    full_width, column_gap = 168 * mm, 9 * mm
    column_width = (full_width - column_gap) / 2
    body_height = A4[1] - 2 * margin_y - 2 * mm
    zh_cover, zh_body = parse_source(ZH_SOURCE, "zh", column_width)
    en_cover, en_body = parse_source(EN_SOURCE, "en", column_width)
    story = zh_cover + [NextPageTemplate("body"), PageBreak()] + zh_body
    story += [NextPageTemplate("cover"), PageBreak()] + en_cover
    story += [NextPageTemplate("body"), PageBreak()] + en_body
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=margin_x, rightMargin=margin_x,
        topMargin=margin_y, bottomMargin=margin_y,
        title="LamTools：具备能力感知委派机制的本地优先 Agent 运行时 / LamTools: A Local-First Agent Runtime with Capability-Aware Delegation",
        author="Yulin Zhang; Yiming Zhang",
        subject="Technical paper on the LamTools local-first agent runtime",
        creator="LamTools paper generator",
        keywords="AI agents; model delegation; multimodal capability; durable execution; local-first software; retrieval evaluation; reproducibility")
    cover_frame = Frame(margin_x, margin_y, full_width, A4[1] - 2 * margin_y, id="cover")
    left = Frame(margin_x, margin_y, column_width, body_height, id="left")
    right = Frame(margin_x + column_width + column_gap, margin_y, column_width, body_height, id="right")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[cover_frame], onPage=decorate_page),
                          PageTemplate(id="body", frames=[left, right], onPage=decorate_page)])
    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    main()
