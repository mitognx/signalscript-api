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


def normalize_transcript(data):
    lines = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                start = item.get("start") or item.get("offset") or 0

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
        for p in str(data).split("\n"):
            if p.strip():
                lines.append({
                    "timestamp": "",
                    "text": p.strip()
                })

    return [l for l in lines if l["text"]]


def transcript_to_plain(lines, max_chars=18000):
    text = "\n".join([f"[{l['timestamp']}] {l['text']}" for l in lines])
    return text[:max_chars]


def get_video_title(url):
    try:
        res = requests.get(
            "https://api.supadata.ai/v1/youtube/video",
            params={"url": url},
            headers={"x-api-key": os.environ.get("SUPADATA_API_KEY")},
            timeout=10
        )
        data = res.json()
        return data.get("title", "YouTube Video Report")
    except Exception:
        return "YouTube Video Report"


def generate_ai_summary(lines):
    key = os.environ.get("OPENAI_API_KEY")

    if not key:
        return {
            "summary": "Summary unavailable because OPENAI_API_KEY is not set.",
            "takeaways": []
        }

    text = transcript_to_plain(lines)

    prompt = f"""
Create a concise summary and 5 key takeaways from this YouTube transcript.

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
{text}
"""

    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            json={
                "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                "input": prompt,
                "store": False
            },
            timeout=60
        )

        out = r.json().get("output_text", "")

        if not out:
            return {
                "summary": "AI summary unavailable.",
                "takeaways": []
            }

        summary = out.replace("SUMMARY:", "").strip()
        takeaways = []

        if "KEY TAKEAWAYS:" in out:
            parts = out.split("KEY TAKEAWAYS:")
            summary = parts[0].replace("SUMMARY:", "").strip()

            takeaways = [
                l.strip("- ").strip()
                for l in parts[1].split("\n")
                if l.strip().startswith("-")
            ]

        return {
            "summary": summary,
            "takeaways": takeaways
        }

    except Exception:
        return {
            "summary": "AI summary unavailable.",
            "takeaways": []
        }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(50, 28, "SignalScript Report")
    canvas.drawRightString(562, 28, f"Page {doc.page}")
    canvas.restoreState()


def create_pdf(transcript_data, title, pdf_path):
    lines = normalize_transcript(transcript_data)
    ai = generate_ai_summary(lines)

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
        fontSize=24,
        leading=30,
        spaceAfter=20
    )

    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=12,
        textColor=colors.grey,
        spaceAfter=20
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Heading2"],
        textColor=colors.blue,
        spaceAfter=10
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=15,
        spaceAfter=8
    )

    timestamp_style = ParagraphStyle(
        "TimestampStyle",
        parent=styles["Heading4"],
        textColor=colors.blue,
        fontSize=9,
        leading=12,
        spaceAfter=3
    )

    content = []

    content.append(Spacer(1, 120))
    content.append(Paragraph(html.escape(title), title_style))
    content.append(Paragraph("YouTube Transcript Report", subtitle_style))
    content.append(Paragraph("Summary • Key Takeaways • Timestamped Transcript", subtitle_style))
    content.append(PageBreak())

    content.append(Paragraph("Summary", section_style))
    content.append(Paragraph(html.escape(ai["summary"]), body_style))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Key Takeaways", section_style))

    if ai["takeaways"]:
        for t in ai["takeaways"]:
            content.append(Paragraph(f"• {html.escape(t)}", body_style))
    else:
        content.append(Paragraph("No key takeaways were generated.", body_style))

    content.append(PageBreak())

    content.append(Paragraph("Transcript", title_style))

    for l in lines:
        if l["timestamp"]:
            content.append(Paragraph(l["timestamp"], timestamp_style))

        content.append(Paragraph(html.escape(l["text"]), body_style))
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
        key = os.environ.get("SUPADATA_API_KEY")

        if not key:
            return jsonify({"error": "Missing SUPADATA_API_KEY"}), 500

        r = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": key},
            timeout=60
        )

        result = r.json()

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
        return jsonify({"error": "PDF not found or expired. Please generate it again."}), 404

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=safe_name,
        mimetype="application/pdf"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
