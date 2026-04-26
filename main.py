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
import re

app = Flask(__name__)
CORS(app)


@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."


# -------------------------
# HELPERS
# -------------------------

def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name[:80] if name else "transcript"


def seconds_to_timestamp(seconds):
    try:
        seconds = int(float(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except:
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


# -------------------------
# GET VIDEO TITLE
# -------------------------

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
    except:
        return "YouTube Video Report"


# -------------------------
# AI SUMMARY
# -------------------------

def generate_ai_summary(lines):
    key = os.environ.get("OPENAI_API_KEY")

    if not key:
        return {
            "summary": "Summary unavailable.",
            "takeaways": []
        }

    text = transcript_to_plain(lines)

    prompt = f"""
Create a concise summary and 5 key takeaways.

SUMMARY:
1 paragraph

KEY TAKEAWAYS:
- ...
- ...
- ...
- ...
- ...

{text}
"""

    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4.1-mini",
            "input": prompt
        },
        timeout=60
    )

    out = r.json().get("output_text", "")

    summary = out
    takeaways = []

    if "KEY TAKEAWAYS:" in out:
        parts = out.split("KEY TAKEAWAYS:")
        summary = parts[0].replace("SUMMARY:", "").strip()

        takeaways = [
            l.strip("- ").strip()
            for l in parts[1].split("\n")
            if l.strip().startswith("-")
        ]

    return {"summary": summary, "takeaways": takeaways}


# -------------------------
# PDF
# -------------------------

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(50, 28, "SignalScript Report")
    canvas.drawRightString(562, 28, f"Page {doc.page}")
    canvas.restoreState()


def create_pdf(transcript_data, title):
    lines = normalize_transcript(transcript_data)
    ai = generate_ai_summary(lines)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(path, pagesize=letter)

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontSize=24,
        leading=30,
        spaceAfter=20
    )

    subtitle = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontSize=12,
        textColor=colors.grey,
        spaceAfter=20
    )

    section = ParagraphStyle(
        "section",
        parent=styles["Heading2"],
        textColor=colors.blue,
        spaceAfter=10
    )

    body = styles["Normal"]

    content = []

    # COVER PAGE
    content.append(Spacer(1, 120))
    content.append(Paragraph(html.escape(title), title_style))
    content.append(Paragraph("YouTube Transcript Report", subtitle))
    content.append(PageBreak())

    # SUMMARY
    content.append(Paragraph("Summary", section))
    content.append(Paragraph(html.escape(ai["summary"]), body))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Key Takeaways", section))
    for t in ai["takeaways"]:
        content.append(Paragraph(f"• {html.escape(t)}", body))

    content.append(PageBreak())

    # TRANSCRIPT
    content.append(Paragraph("Transcript", title_style))

    for l in lines:
        if l["timestamp"]:
            content.append(Paragraph(l["timestamp"], styles["Heading4"]))

        content.append(Paragraph(html.escape(l["text"]), body))
        content.append(Spacer(1, 6))

    doc.build(content, onFirstPage=footer, onLaterPages=footer)

    return path


# -------------------------
# ROUTE
# -------------------------

@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    try:
        key = os.environ.get("SUPADATA_API_KEY")

        r = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": key}
        )

        result = r.json()

        if "transcript" in result:
            data = result["transcript"]
        elif "content" in result:
            data = result["content"]
        else:
            return jsonify(result), 400

        title = get_video_title(url)

        pdf = create_pdf(data, title)

        filename = clean_filename(title) + ".pdf"

        return send_file(
            pdf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
