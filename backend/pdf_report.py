from __future__ import annotations

import io
from html import escape
from pathlib import Path
from typing import Any


def build_report_pdf(report: dict[str, Any], *, organization_name: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise ValueError("Máy chủ chưa cài thư viện reportlab để xuất PDF.") from error

    font_name = _register_unicode_font(pdfmetrics, TTFont)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MinhChungTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=23,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#164b3d"),
    )
    heading_style = ParagraphStyle(
        "MinhChungHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#164b3d"),
        spaceBefore=6,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "MinhChungBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#263b34"),
    )
    small_style = ParagraphStyle(
        "MinhChungSmall",
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#62736d"),
    )

    result = report["result"]
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Báo cáo tương đồng - {report['title']}",
        author="Minh Chứng",
    )
    story = [
        Paragraph("MINH CHỨNG", title_style),
        Paragraph("BÁO CÁO TƯƠNG ĐỒNG VĂN BẢN", title_style),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Tổ chức:</b> {escape(organization_name)}", body_style),
        Paragraph(f"<b>Tài liệu:</b> {escape(report['title'])}", body_style),
        Paragraph(f"<b>Ngày tạo:</b> {escape(report['created_at'])}", small_style),
        Spacer(1, 4 * mm),
    ]

    summary = [
        ["Tỷ lệ tương đồng", "Số từ", "Từ trùng", "Nguồn liên quan", "Cảnh báo toàn vẹn"],
        [
            f"{int(result.get('percent', 0))}%",
            str(int(result.get("totalWords", 0))),
            str(int(result.get("matchedWords", 0))),
            str(len(result.get("sources", []))),
            str(len(result.get("integrityFlags", []))),
        ],
    ]
    summary_table = Table(summary, colWidths=[35 * mm, 25 * mm, 25 * mm, 35 * mm, 42 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#164b3d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f6f2")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce5df")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 4 * mm)])

    story.append(Paragraph("Nguồn liên quan", heading_style))
    sources = result.get("sources", [])
    if sources:
        source_rows = [["Nguồn", "Loại", "Đoạn", "Số từ"]]
        for source in sources:
            source_rows.append(
                [
                    Paragraph(f"{escape(source['title'])}<br/><font size='7'>{escape(source['url'])}</font>", small_style),
                    escape(str(source.get("type", ""))),
                    str(int(source.get("matches", 0))),
                    str(int(source.get("matchedWords", 0))),
                ]
            )
        table = Table(source_rows, colWidths=[95 * mm, 27 * mm, 18 * mm, 20 * mm], repeatRows=1)
        table.setStyle(_data_table_style(colors, font_name))
        story.extend([table, Spacer(1, 4 * mm)])
    else:
        story.append(Paragraph("Chưa phát hiện nguồn tương đồng đáng kể.", body_style))

    story.append(Paragraph("Đoạn cần rà soát", heading_style))
    matched_segments = result.get("matchedSegments", [])
    if matched_segments:
        for segment in matched_segments:
            source = segment.get("source", {})
            story.append(
                Paragraph(
                    f"<b>#{int(segment.get('number', 0))} · {int(segment.get('confidence', 0))}% · "
                    f"{escape(source.get('title', 'Nguồn chưa xác định'))}</b><br/>"
                    f"{escape(segment.get('text', '').strip())}",
                    body_style,
                )
            )
            story.append(Spacer(1, 2 * mm))
    else:
        story.append(Paragraph("Không có đoạn nào vượt ngưỡng hiện tại.", body_style))

    story.append(Paragraph("Cảnh báo toàn vẹn", heading_style))
    flags = result.get("integrityFlags", [])
    if flags:
        for flag in flags:
            story.append(
                Paragraph(
                    f"<b>{escape(flag.get('message', 'Cảnh báo'))}</b> "
                    f"({escape(str(flag.get('severity', 'cần xem')))})",
                    body_style,
                )
            )
    else:
        story.append(Paragraph("Chưa phát hiện thủ thuật định dạng đáng chú ý.", body_style))

    story.extend(
        [
            Spacer(1, 5 * mm),
            Paragraph(
                "Lưu ý: tỷ lệ tương đồng là tín hiệu hỗ trợ rà soát, không phải kết luận tự động về đạo văn.",
                small_style,
            ),
        ]
    )
    document.build(story)
    return buffer.getvalue()


def _register_unicode_font(pdfmetrics: Any, tt_font: Any) -> str:
    candidates = [
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            name = "MinhChungUnicode"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(tt_font(name, str(path)))
            return name
    return "Helvetica"


def _data_table_style(colors: Any, font_name: str) -> Any:
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dff0e8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#164b3d")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce5df")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )

