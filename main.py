from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

import requests
import os
import html
import re
import uuid

app = Flask(__name__)
CORS(app)

PDF_DIR = "/tmp/signalscript_pdfs"
os.makedirs(PDF_DIR, exist_ok=True)


@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."


def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:80] if name else "youtube_transcript_report"


def seconds_to_timestamp(seconds):
    try:
        seconds = int(float(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return "00:00:00"


def get_video_title(url):
    try:
        res = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10
        )
        data = res.json()
        return data.get("title", "YouTube Transcript Report")
    except Exception:
        return "YouTube Transcript Report"


def normalize_transcript(data):
    lines = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                start = item.get("start") or item.get("offset") or 0

                try:
                    start_num = float(start)

                    # Supadata may return milliseconds instead of seconds.
                    if start_num > 10000:
                        start_num = start_num / 1000

                except Exception:
                    start_num = 0

                lines.append({
                    "timestamp": seconds_to_timestamp(start_num),
                    "start": start_num,
                    "text": str(text).strip()
                })

            else:
                lines.append({
                    "timestamp": "",
                    "start": 0,
                    "text": str(item).strip()
                })

    else:
        for paragraph in str(data).split("\n"):
            if paragraph.strip():
                lines.append({
                    "timestamp": "",
                    "start": 0,
                    "text": paragraph.strip()
                })

    return [line for line in lines if line["text"]]


def group_transcript(lines, max_words=90):
    grouped = []
    current_text = []
    current_start = None
    word_count = 0

    for line in lines:
        text = line["text"]
        words = text.split()

        if current_start is None:
            current_start = line["start"]

        current_text.append(text)
        word_count += len(words)

        ends_sentence = text.endswith((".", "?", "!"))
        enough_words = word_count >= max_words

        if (ends_sentence and word_count >= 35) or enough_words:
            grouped.append({
                "timestamp": seconds_to_timestamp(current_start),
                "text": " ".join(current_text)
            })

            current_text = []
            current_start = None
            word_count = 0

    if current_text:
        grouped.append({
            "timestamp": seconds_to_timestamp(current_start or 0),
            "text": " ".join(current_text)
        })

    return grouped


def transcript_to_plain(grouped, max_chars=22000):
    text = "\n\n".join([
        f"[{item['timestamp']}] {item['text']}"
        for item in grouped
    ])

    return text[:max_chars]


def extract_openai_text(result):
    """
    Safely extracts text from OpenAI Responses API output.
    """

    if result.get("output_text"):
        return result.get("output_text", "")

    output_text = ""

    for item in result.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text += content.get("text", "")

    return output_text.strip()


def generate_ai_summary(grouped):
    openai_key = os.environ.get("OPENAI_API_KEY")

    if not openai_key:
        return {
            "summary": "AI summary unavailable because OPENAI_API_KEY is not set in Render.",
            "takeaways": [
                "The transcript PDF was generated successfully.",
                "Add OPENAI_API_KEY in Render to enable summary and key takeaways."
            ]
        }

    transcript_text = transcript_to_plain(grouped)

    prompt = f"""
Create a concise executive summary and 5 useful key takeaways from this YouTube transcript.

Return ONLY this exact format:

SUMMARY:
One clear paragraph.

KEY TAKEAWAYS:
- Takeaway 1
- Takeaway 2
- Takeaway 3
- Takeaway 4
- Takeaway 5

Transcript:
{transcript_text}
"""

    try:
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
        output_text = extract_openai_text(result)

        if not output_text:
            return {
                "summary": "AI summary unavailable from the model response.",
                "takeaways": [
                    "The transcript was generated successfully.",
                    "The AI summary step returned an empty response."
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

        if not takeaways:
            takeaways = [
                "The transcript was generated successfully.",
                "The video content has been organized into a readable report.",
                "The full timestamped transcript is included after the summary section."
            ]

        return {
            "summary": summary,
            "takeaways": takeaways
        }

    except Exception as e:
        return {
            "summary": f"AI summary unavailable: {str(e)}",
            "takeaways": [
                "The transcript PDF was generated successfully.",
                "The AI summary step failed, but the transcript is included."
            ]
        }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(50, 28, "SignalScript Report")
    canvas.drawRightString(562, 28, f"Page {doc.page}")
    canvas.restoreState()


def create_pdf(transcript_data, title, pdf_path):
    raw_lines = normalize_transcript(transcript_data)
    grouped = group_transcript(raw_lines)
    ai = generate_ai_summary(grouped)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=55,
        leftMargin=55,
        topMargin=55,
        bottomMargin=55
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=30,
        alignment=1,
        spaceAfter=22
    )

    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=12,
        leading=18,
        textColor=colors.grey,
        alignment=1,
        spaceAfter=14
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=22,
        textColor=colors.HexColor("#146EF5"),
        spaceBefore=8,
        spaceAfter=12
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=16,
        spaceAfter=10
    )

    timestamp_style = ParagraphStyle(
        "TimestampStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#146EF5"),
        spaceBefore=8,
        spaceAfter=3
    )

    content = []

    # Cover page
    content.append(Spacer(1, 120))
    content.append(Paragraph(html.escape(title), title_style))
    content.append(Paragraph("YouTube Transcript Report", subtitle_style))
    content.append(Paragraph("Summary • Key Takeaways • Readable Timestamped Transcript", subtitle_style))
    content.append(PageBreak())

    # Summary page
    content.append(Paragraph("Summary", section_style))
    content.append(Paragraph(html.escape(ai["summary"]), body_style))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Key Takeaways", section_style))

    for takeaway in ai["takeaways"]:
        content.append(Paragraph(f"• {html.escape(takeaway)}", body_style))

    content.append(PageBreak())

    # Transcript page
    content.append(Paragraph("Transcript", title_style))

    for item in grouped:
        content.append(Paragraph(item["timestamp"], timestamp_style))
        content.append(Paragraph(html.escape(item["text"]), body_style))
        content.append(Spacer(1, 6))

    doc.build(content, onFirstPage=footer, onLaterPages=footer)

    return pdf_path


@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url") if data else None

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        supadata_key = os.environ.get("SUPADATA_API_KEY")

        if not supadata_key:
            return jsonify({"error": "Missing SUPADATA_API_KEY"}), 500

        response = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": supadata_key},
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

        title = get_video_title(url)
        safe_title = clean_filename(title)
        file_id = str(uuid.uuid4())

        filename = f"{safe_title}-{file_id}.pdf"
        pdf_path = os.path.join(PDF_DIR, filename)

        create_pdf(transcript_data, title, pdf_path)

        base_url = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
        download_url = f"{base_url}/download/{filename}"

        return jsonify({
            "message": "PDF report generated successfully.",
            "title": title,
            "filename": filename,
            "download_url": download_url
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/download/<filename>", methods=["GET"])
def download_pdf(filename):
    safe_name = os.path.basename(filename)
    pdf_path = os.path.join(PDF_DIR, safe_name)

    if not os.path.exists(pdf_path):
        return jsonify({
            "error": "PDF not found or expired. Please generate it again."
        }), 404

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=safe_name,
        mimetype="application/pdf"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
