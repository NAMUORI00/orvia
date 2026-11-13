import io, pathlib
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

pdfmetrics.registerFont(
    TTFont(
        "Nanum", str(pathlib.Path(__file__).parent / "fonts/NanumGothic-Regular.ttf")
    )
)


def make_pdf(document):
    lang = document["language"]
    tr = lambda ko, en: ko if lang == "ko" else en
    body = ParagraphStyle(
        "body",
        fontName="Nanum",
        fontSize=9,
        leading=14,
        wordWrap="CJK",
        textColor=colors.HexColor("#233c48"),
    )
    head = ParagraphStyle("head", parent=body, fontSize=22, leading=30, spaceAfter=12)
    p = lambda s: Paragraph(escape(str(s)).replace("\n", "<br/>"), body)
    story = [
        Paragraph(tr("연구실 접속 안내서", "Laboratory access guide"), head),
        p(document["title"]),
        Spacer(1, 18),
    ]

    def table(rows, widths, header=True):
        t = Table(
            [[p(v) for v in row] for row in rows],
            colWidths=widths,
            repeatRows=1 if header else 0,
            hAlign="LEFT",
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9f3f3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#dce6e8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.extend([t, Spacer(1, 15)])

    table([[tr("접속 주소", "Server address"), document["host"]]], [120, 375])
    rows = [
        [
            tr("계정 ID", "Account ID"),
            tr("사용자명", "Name"),
            tr("SSH 포트", "SSH port"),
        ]
    ]
    rows += [
        [u["id"], u.get("display_name", "N/A"), u["port"]] for u in document["accounts"]
    ]
    if len(rows) == 1:
        rows.append(["N/A", "N/A", "N/A"])
    table(rows, [200, 200, 95])
    table(
        [[tr("사용 가능한 자원", "Available resources"), tr("사양", "Specification")]]
        + [[r["label"], r["value"]] for r in document["resources"]],
        [120, 375],
    )
    if document["shared_memory"]:
        story.extend(
            [
                p(
                    tr(
                        "시스템 메모리는 모든 서버 이용자가 공유합니다.",
                        "System memory is shared by all server users.",
                    )
                ),
                Spacer(1, 10),
            ]
        )
    story.extend([p(tr("접속 명령", "Connection commands")), Spacer(1, 6)])
    for u in document["accounts"]:
        story.append(p(u["command"]))
    if document["note"]:
        story.extend([Spacer(1, 12), p(document["note"])])
    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=44,
        bottomMargin=42,
        title=tr("연구실 접속 안내서", "Laboratory access guide"),
        author="LabHarbor",
    )

    def footer(c, d):
        c.setFont("Nanum", 8)
        c.setFillColor(colors.HexColor("#728a95"))
        c.drawString(50, 23, "LabHarbor")
        c.drawRightString(A4[0] - 50, 23, str(d.page))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    stream.seek(0)
    return stream
