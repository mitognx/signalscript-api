from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

import requests
import os
import tempfile
import html

app = Flask(__name__)
CORS(app)


@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."


def seconds_to_timestamp(seconds):
    try:
        seconds = int(float(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return "00:00:00"


def normalize_transcript(transcript_data):
    lines = []

    if isinstance(transcript_data, list):
        for item in transcript_data:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                start = item.get("start") or item.get("offset") or item.get("startTime") or 0

                lines.append({
                    "timestamp": seconds_to_timestamp(start),
                    "text": str(text).strip()
                })
            else:
                lines.append({
                    "timestamp": "",
                    "text": str(item).strip()
                })
    else:
        for paragraph in str(transcript_data).split("\n"):
            if paragraph.strip():
                lines.append({
                    "timestamp": "",
                    "text": paragraph.strip()
                })

    return [line for line in lines if line["text"]]


def transcript_to_plain_text(lines, max_chars=18000):
    text = "\n".join([
        f"[{line['timestamp']}] {line['text']}"
        for line in lines
    ])
    return text[:max_chars]


def generate_ai_summary(lines):
    openai_key = os.environ.get("OPENAI_API_KEY")

    if not openai_key:
        return {
            "summary": "AI summary unavailable because OPENAI_API_KEY is not set.",
            "takeaways": [
                "Transcript PDF was generated successfully.",
                "Add OPENAI_API_KEY in Render to enable AI summary and key takeaways."
            ]
        }

    transcript_text = transcript_to_plain_text(lines)

    prompt = f"""
Create a clean executive summary and key takeaways from this YouTube transcript.

Return ONLY this format:

SUMMARY:
One concise paragraph.

KEY TAKEAWAYS:
- takeaway 1
- takeaway 2
- takeaway 3
- takeaway 4
- takeaway 5

Transcript:
{transcript_text}
"""

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "input": prompt,
            "store": False
        },
        timeout=60
    )

    result = response.json()
    output_text = result.get("output_text", "")

    if not output_text:
        return {
            "summary": "AI summary unavailable.",
            "takeaways": [
                "The transcript was successfully exported.",
                "The AI summary could not be generated from the current response."
            ]
        }

    summary = output_text.replace("SUMMARY:", "").strip()
    takeaways = []

    if "KEY TAKEAWAYS:" in output_text:
        parts = output_text.split("KEY TAKEAWAYS:")
        summary = parts[0].replace("SUMMARY:", "").strip()

        takeaways = [
            line.strip("- ").strip()
            for line in parts[1].split("\n")
            if line.strip().startswith("-")
        ]

    return {
        "summary": summary,
        "takeaways": takeaways
    }


def pdf_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5A5A5A"))
    canvas.drawString(50, 28, "SignalScript Transcript Report")
    canvas.drawRightString(562, 28, f"Page {doc.page}")
    canvas.restoreState()


def create_transcript_pdf(transcript_data):
    lines = normalize_transcript(transcript_data)
    ai = generate_ai_summary(lines)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf_path = temp_file.name
    temp_file.close()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#080808"),
        spaceAfter=20
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=20,
        textColor=colors.HexColor("#146EF5"),
        spaceBefore=12,
        spaceAfter=10
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#171717"),
        spaceAfter=8
    )

    timestamp_style = ParagraphStyle(
        "TimestampStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#146EF5")
    )

    content = []

    content.append(Paragraph("SignalScript Transcript Report", title_style))

    content.append(Paragraph("AI Summary", section_style))
    content.append(Paragraph(html.escape(ai["summary"]), body_style))

    content.append(Spacer(1, 10))
    content.append(Paragraph("Key Takeaways", section_style))

    for takeaway in ai["takeaways"]:
        content.append(Paragraph(f"• {html.escape(takeaway)}", body_style))

    content.append(PageBreak())
    content.append(Paragraph("Full Transcript", title_style))

    for line in lines:
        if line["timestamp"]:
            content.append(Paragraph(line["timestamp"], timestamp_style))

        content.append(Paragraph(html.escape(line["text"]), body_style))
        content.append(Spacer(1, 4))

    doc.build(
        content,
        onFirstPage=pdf_footer,
        onLaterPages=pdf_footer
    )

    return pdf_path


@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "Missing YouTube URL"}), 400

    try:
        api_key = os.environ.get("SUPADATA_API_KEY")

        if not api_key:
            return jsonify({"error": "Missing SUPADATA_API_KEY"}), 500

        response = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": api_key},
            timeout=60
        )

        result = response.json()

        if "transcript" in result:
            transcript_data = result["transcript"]
        elif "content" in result:
            transcript_data = result["content"]
        else:
            return jsonify({
                "error": "Transcript unavailable",
                "details": result
            }), 400

        pdf_path = create_transcript_pdf(transcript_data)

        return send_file(
            pdf_path,
            as_attachment=True,
            download_name="signalscript_transcript_report.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
