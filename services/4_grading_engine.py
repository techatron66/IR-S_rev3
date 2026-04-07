"""
IRIS v2 — Grading Engine Service
Port: 8003
Full OCR pipeline + AI grading + PDF export
"""
import sys
import os

# Add parent directory to python path for running directly from services folder
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, _ROOT)

import asyncio
import base64
import csv
import io
import json
import re
import statistics
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber
import pytesseract
from fastapi import (
    FastAPI, BackgroundTasks, Depends, HTTPException,
    UploadFile, File, Form, Header, Request
)
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pdf2image import convert_from_path
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from sqlmodel import Session, select

from core.config import settings
from core.database import get_session, init_db, engine
from core.models import (
    Exam, ExamQuestion, StudentAnswer, GradingJob,
    Student, ClassRoom, AuditLog, Notification
)
from core.nv_client import nv_client

# ─── Setup ────────────────────────────────────────────────────────────────────

EXAM_DB = Path(_ROOT) / "exam_db"
EXAM_DB.mkdir(exist_ok=True)

app = FastAPI(title="IRIS Grading Engine", version="2.0")


@app.on_event("startup")
def startup():
    init_db()
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


# ─── GRADING PROMPT ───────────────────────────────────────────────────────────

GRADING_SYSTEM_PROMPT = """You are an expert academic examiner with deep subject matter expertise.
Your task is to evaluate a student's answer to a specific exam question.

Scoring rules:
- Score the SEMANTIC CORRELATION between the student answer and the reference answer on a scale of 0.0 to 1.0
- 1.0 = complete, accurate, well-articulated answer covering all key concepts
- 0.7-0.9 = mostly correct, minor gaps or imprecision
- 0.4-0.6 = partially correct, missing important concepts but shows understanding
- 0.1-0.3 = mostly incorrect, minimal relevant content
- 0.0 = completely wrong, off-topic, or blank

Additional rules:
- Consider CONCEPTUAL UNDERSTANDING, not just keyword matching
- Accept valid alternative explanations not in the reference answer
- Be fair but rigorous — partial credit should be earned, not given freely
- Provide specific, actionable feedback the student can learn from

Output ONLY valid JSON matching this exact schema:
{
  "correlation_score": <float between 0.0 and 1.0>,
  "awarded_marks": <float — correlation_score multiplied by max_marks>,
  "rationale": "<one sentence explaining the score>",
  "feedback": "<1-2 sentences of constructive improvement feedback for the student>",
  "missing_concepts": ["<concept1>", "<concept2>"]
}"""


# ─── OCR PIPELINE ─────────────────────────────────────────────────────────────

async def route_ocr(pdf_path: str) -> tuple:
    """
    Smart OCR routing:
    1. pdfplumber (digital PDF — instant, free)
    2. pytesseract (typed scan — fast, local)
    3. NV Vision LLM (handwriting — accurate, paid)
    Returns: (extracted_text, method_used)
    """
    threshold = settings.OCR_HANDWRITING_THRESHOLD

    # Stage 1: pdfplumber (digital PDFs)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if len(text.strip()) >= threshold:
            return text.strip(), "pdfplumber"
    except Exception:
        pass

    # Stage 2: Convert to images for raster OCR
    try:
        images = convert_from_path(pdf_path, dpi=200)
    except Exception:
        images = []

    # Stage 3: Tesseract (printed/scanned text)
    if images:
        try:
            tesseract_text = "\n".join(
                pytesseract.image_to_string(img, lang="eng", config="--psm 6")
                for img in images
            )
            if len(tesseract_text.strip()) >= threshold:
                return tesseract_text.strip(), "tesseract"
        except Exception:
            pass

    # Stage 4: NV Vision LLM (handwritten answers)
    if images:
        vision_pages = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            try:
                page_text = await nv_client.vision_ocr(b64)
                vision_pages.append(page_text)
            except Exception as e:
                vision_pages.append(f"[OCR Error: {e}]")
        return "\n".join(vision_pages), "vision_llm"

    return "", "none"


async def segment_answers_by_question(raw_text: str, question_count: int) -> dict:
    """Use Kimi K2.5 to split answer sheet text by question number."""
    prompt = (
        f"The following is a student's complete exam answer sheet text (OCR'd).\n"
        f"Split it into exactly {question_count} separate answers.\n\n"
        f"Rules:\n"
        f"- Look for markers like 'Q1', 'Question 1', '1.', 'Ans 1', '(1)'\n"
        f"- If question markers are missing, split by logical paragraph boundaries\n"
        f"- If fewer than {question_count} answers are detectable, fill missing ones with empty string\n"
        f"- Return ONLY valid JSON: {{\"1\": \"answer text...\", \"2\": \"...\", ...}}\n\n"
        f"Answer sheet text:\n{raw_text[:8000]}"
    )
    try:
        response = await nv_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
            max_tokens=2048,
        )
        raw = json.loads(response)
        return {int(k): v for k, v in raw.items()}
    except Exception:
        # Fallback: naive line-based split
        lines = raw_text.split("\n")
        chunk_size = max(1, len(lines) // question_count)
        return {
            i + 1: "\n".join(lines[i * chunk_size:(i + 1) * chunk_size])
            for i in range(question_count)
        }


async def grade_answer(
    question_text: str,
    reference_answer: str,
    student_answer: str,
    max_marks: float,
) -> dict:
    """Call Kimi K2.5 to semantically grade one answer. Returns grading dict."""
    user_msg = (
        f"Question: {question_text}\n"
        f"Reference Answer: {reference_answer or '(No reference provided — grade based on question)'}\n"
        f"Student Answer: {student_answer or '(blank)'}\n"
        f"Maximum Marks: {max_marks}\n\n"
        f"Evaluate and return JSON only."
    )
    try:
        response = await nv_client.chat_completion(
            messages=[
                {"role": "system", "content": GRADING_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            json_mode=True,
            temperature=0.1,
            max_tokens=512,
        )
        result = json.loads(response)
        result["correlation_score"] = max(0.0, min(1.0, float(result.get("correlation_score", 0))))
        result["awarded_marks"] = round(result["correlation_score"] * max_marks, 2)
        return result
    except Exception:
        return {
            "correlation_score": 0.0,
            "awarded_marks": 0.0,
            "rationale": "Grading failed — manual review required",
            "feedback": "Unable to process this answer automatically.",
            "missing_concepts": [],
        }


# ─── BACKGROUND GRADING PIPELINE ──────────────────────────────────────────────

async def run_grading_pipeline(job_id: int, exam_id: int, sheet_paths: list):
    """
    Full async grading pipeline for one exam job.
    Processes each sheet sequentially; grades questions concurrently.
    Updates GradingJob progress in DB after each sheet.
    """
    from sqlmodel import Session as DBSession

    with DBSession(engine) as db:
        job = db.get(GradingJob, job_id)
        if not job:
            return
        job.status = "processing"
        job.started_at = datetime.utcnow()
        db.add(job)
        db.commit()

        questions = db.exec(
            select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
        ).all()

        for sheet_path in sheet_paths:
            roll_no = Path(sheet_path).stem
            try:
                # 1. Find student record
                student = db.exec(
                    select(Student).where(Student.roll_number == roll_no)
                ).first()
                if not student:
                    job.failed_sheets += 1
                    job.error_log = (job.error_log or "") + f"\n{roll_no}: Student not found in DB"
                    db.add(job)
                    db.commit()
                    continue

                # 2. OCR
                raw_text, ocr_method = await route_ocr(sheet_path)

                # Save OCR result
                ocr_dir = EXAM_DB / str(exam_id) / "sheets" / "ocr"
                ocr_dir.mkdir(parents=True, exist_ok=True)
                (ocr_dir / f"{roll_no}.json").write_text(
                    json.dumps({"ocr_method": ocr_method, "text": raw_text}, indent=2),
                    encoding="utf-8"
                )

                if len(raw_text.strip()) < 10:
                    for q in questions:
                        ans = StudentAnswer(
                            exam_id=exam_id,
                            student_id=student.id,
                            question_id=q.id,
                            raw_ocr_text="",
                            status="manual_review",
                        )
                        db.add(ans)
                    db.commit()
                    job.processed_sheets += 1
                    db.add(job)
                    db.commit()
                    continue

                # 3. Segment answers
                answer_map = await segment_answers_by_question(raw_text, len(questions))

                # 4. Grade all questions concurrently
                async def grade_one(q: ExamQuestion, student_ans: str):
                    result = await grade_answer(
                        q.question_text,
                        q.reference_answer or "",
                        student_ans,
                        q.max_marks,
                    )
                    return q, result

                tasks = [
                    grade_one(q, answer_map.get(q.q_number, ""))
                    for q in questions
                ]
                graded = await asyncio.gather(*tasks, return_exceptions=True)

                # 5. Persist results
                for item in graded:
                    if isinstance(item, Exception):
                        continue
                    q, result = item
                    ans = StudentAnswer(
                        exam_id=exam_id,
                        student_id=student.id,
                        question_id=q.id,
                        raw_ocr_text=answer_map.get(q.q_number, ""),
                        correlation_score=result["correlation_score"],
                        awarded_marks=result["awarded_marks"],
                        ai_rationale=result.get("rationale", ""),
                        ai_feedback=result.get("feedback", ""),
                        missing_concepts=json.dumps(result.get("missing_concepts", [])),
                        status="graded",
                    )
                    db.add(ans)

                db.commit()
                job.processed_sheets += 1
                db.add(job)
                db.commit()

            except Exception as e:
                job.failed_sheets += 1
                job.error_log = (job.error_log or "") + f"\n{roll_no}: {str(e)}"
                db.add(job)
                db.commit()

        # Finalize
        job.status = "completed" if job.failed_sheets == 0 else "completed_with_errors"
        job.completed_at = datetime.utcnow()
        db.add(job)
        db.commit()


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _get_grade_letter(pct: float) -> str:
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B"
    if pct >= 60: return "C"
    if pct >= 40: return "D"
    return "F"


def _compute_results(exam_id: int, db: Session) -> dict:
    """Build full results dict for an exam."""
    exam = db.get(Exam, exam_id)
    if not exam:
        return {}

    questions = db.exec(
        select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
    ).all()
    q_map = {q.id: q for q in questions}

    answers = db.exec(
        select(StudentAnswer).where(StudentAnswer.exam_id == exam_id)
    ).all()

    # Group by student
    from collections import defaultdict
    by_student = defaultdict(list)
    for ans in answers:
        by_student[ans.student_id].append(ans)

    student_results = []
    totals = []
    for stu_id, ans_list in by_student.items():
        student = db.get(Student, stu_id)
        if not student:
            continue
        total = sum(
            (a.professor_override if a.professor_override is not None else a.awarded_marks)
            for a in ans_list
        )
        totals.append(total)
        pct = round(total / exam.total_marks * 100, 1) if exam.total_marks else 0.0
        grade_letter = _get_grade_letter(pct)
        q_breakdown = []
        for a in sorted(ans_list, key=lambda x: x.question_id):
            q = q_map.get(a.question_id)
            if q:
                q_breakdown.append({
                    "q_number": q.q_number,
                    "question_text": q.question_text[:200],
                    "max_marks": q.max_marks,
                    "awarded_marks": a.professor_override if a.professor_override is not None else a.awarded_marks,
                    "original_marks": a.awarded_marks,
                    "overridden": a.professor_override is not None,
                    "ai_rationale": a.ai_rationale,
                    "ai_feedback": a.ai_feedback,
                    "missing_concepts": json.loads(a.missing_concepts or "[]"),
                    "status": a.status,
                })
        student_results.append({
            "student_id": stu_id,
            "roll_number": student.roll_number,
            "name": student.name,
            "total": round(total, 2),
            "percentage": pct,
            "grade": grade_letter,
            "questions": q_breakdown,
        })

    student_results.sort(key=lambda x: x["total"], reverse=True)
    for rank, sr in enumerate(student_results, 1):
        sr["rank"] = rank

    # Class stats
    if totals:
        mean = round(statistics.mean(totals), 2)
        median = round(statistics.median(totals), 2)
        std_dev = round(statistics.stdev(totals), 2) if len(totals) > 1 else 0.0
        pass_rate = round(sum(1 for t in totals if exam.total_marks and t / exam.total_marks >= 0.4) / len(totals) * 100, 1)
    else:
        mean = median = std_dev = pass_rate = 0.0

    return {
        "exam_id": exam_id,
        "exam_name": exam.exam_name,
        "exam_date": exam.exam_date,
        "total_marks": exam.total_marks,
        "class_stats": {
            "mean": mean,
            "median": median,
            "std_dev": std_dev,
            "pass_rate": pass_rate,
            "total_students": len(totals),
        },
        "students": student_results,
    }


# ─── REST ENDPOINTS ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "grading-engine", "version": "2.0"}


@app.get("/exams")
def list_exams(db: Session = Depends(get_session)):
    exams = db.exec(select(Exam)).all()
    result = []
    for e in exams:
        classroom = db.get(ClassRoom, e.class_id)
        q_count = len(db.exec(select(ExamQuestion).where(ExamQuestion.exam_id == e.id)).all())
        result.append({
            "id": e.id,
            "exam_name": e.exam_name,
            "exam_date": e.exam_date,
            "total_marks": e.total_marks,
            "status": e.status,
            "class_name": f"{classroom.name} ({classroom.batch})" if classroom else "Unknown",
            "question_count": q_count,
            "created_at": e.created_at.isoformat(),
        })
    return result


@app.post("/exam/create")
def create_exam(
    class_id: int = Form(...),
    exam_name: str = Form(...),
    exam_date: str = Form(...),
    questions_json: str = Form(...),   # JSON array
    db: Session = Depends(get_session),
):
    """
    Create exam with questions.
    questions_json: '[{"q_number":1,"question_text":"...","max_marks":10,"reference_answer":"..."}]'
    """
    questions = json.loads(questions_json)
    total = sum(float(q.get("max_marks", 0)) for q in questions)

    exam = Exam(
        class_id=class_id,
        exam_name=exam_name,
        exam_date=exam_date,
        total_marks=total,
        status="draft",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)

    for q in questions:
        db.add(ExamQuestion(
            exam_id=exam.id,
            q_number=int(q["q_number"]),
            question_text=q["question_text"],
            max_marks=float(q.get("max_marks", 10)),
            reference_answer=q.get("reference_answer"),
        ))
    db.commit()

    return {"exam_id": exam.id, "total_marks": total, "question_count": len(questions)}


@app.post("/exam/{exam_id}/upload-question-paper")
async def upload_question_paper(
    exam_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "Exam not found")

    # Validate file size
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    # Save file
    qp_dir = EXAM_DB / str(exam_id)
    qp_dir.mkdir(parents=True, exist_ok=True)
    qp_path = qp_dir / "question_paper.pdf"
    qp_path.write_bytes(content)

    exam.question_paper_path = str(qp_path)
    db.add(exam)
    db.commit()

    # Attempt OCR + auto-detect questions
    try:
        raw_text, ocr_method = await route_ocr(str(qp_path))
        # Extract question-like patterns
        pattern = re.compile(r'(?:Q\.?\s*\d+|Question\s+\d+|\b\d+[\.\)]\s)', re.IGNORECASE)
        matches = pattern.findall(raw_text)
        extracted = [{"pattern": m.strip(), "context": ""} for m in matches[:50]]
    except Exception as e:
        raw_text = ""
        ocr_method = "none"
        extracted = []

    return {
        "exam_id": exam_id,
        "ocr_method": ocr_method,
        "extracted_questions": extracted,
        "raw_text_preview": raw_text[:1000],
        "requires_confirmation": True,
    }


@app.post("/exam/{exam_id}/confirm-questions")
def confirm_questions(
    exam_id: int,
    questions_json: str = Form(...),
    db: Session = Depends(get_session),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "Exam not found")

    questions = json.loads(questions_json)

    # Remove old questions
    old_qs = db.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    for q in old_qs:
        db.delete(q)
    db.commit()

    total = 0.0
    for q in questions:
        mm = float(q.get("max_marks", 10))
        total += mm
        db.add(ExamQuestion(
            exam_id=exam_id,
            q_number=int(q["q_number"]),
            question_text=q["question_text"],
            max_marks=mm,
            reference_answer=q.get("reference_answer"),
        ))

    exam.total_marks = total
    exam.status = "ready"
    db.add(exam)
    db.commit()

    return {"confirmed": True, "question_count": len(questions), "total_marks": total}


@app.post("/exam/{exam_id}/submit-sheets")
async def submit_sheets(
    exam_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_session),
):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "Exam not found")

    sheets_dir = EXAM_DB / str(exam_id) / "sheets" / "raw"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    skipped = []

    roll_pattern = re.compile(r'^\w{2,20}$')

    for upload in files:
        stem = Path(upload.filename).stem
        if not roll_pattern.match(stem):
            skipped.append({"file": upload.filename, "reason": "Invalid roll number format"})
            continue

        content = await upload.read()
        if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            skipped.append({"file": upload.filename, "reason": "File too large"})
            continue

        save_path = sheets_dir / f"{stem}.pdf"
        save_path.write_bytes(content)
        saved_paths.append(str(save_path))

    if not saved_paths:
        raise HTTPException(400, f"No valid sheets uploaded. Skipped: {skipped}")

    job = GradingJob(
        exam_id=exam_id,
        total_sheets=len(saved_paths),
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    exam.status = "grading"
    db.add(exam)
    db.commit()

    background_tasks.add_task(run_grading_pipeline, job.id, exam_id, saved_paths)

    return {
        "job_id": job.id,
        "status": "queued",
        "total_sheets": len(saved_paths),
        "skipped": skipped,
    }


@app.get("/exam/{exam_id}/job/{job_id}/status")
def get_job_status(exam_id: int, job_id: int, db: Session = Depends(get_session)):
    job = db.get(GradingJob, job_id)
    if not job or job.exam_id != exam_id:
        raise HTTPException(404, "Job not found")

    pct = 0.0
    if job.total_sheets > 0:
        pct = round(job.processed_sheets / job.total_sheets * 100, 1)

    return {
        "job_id": job_id,
        "exam_id": exam_id,
        "status": job.status,
        "progress_pct": pct,
        "processed_sheets": job.processed_sheets,
        "total_sheets": job.total_sheets,
        "failed_sheets": job.failed_sheets,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_log": job.error_log,
    }


@app.get("/exam/{exam_id}/results")
def get_results(exam_id: int, db: Session = Depends(get_session)):
    exam = db.get(Exam, exam_id)
    if not exam:
        raise HTTPException(404, "Exam not found")
    return _compute_results(exam_id, db)


@app.get("/exam/{exam_id}/export/csv")
def export_csv(exam_id: int, db: Session = Depends(get_session)):
    results = _compute_results(exam_id, db)
    if not results:
        raise HTTPException(404, "No results found")

    students = results["students"]
    if not students:
        raise HTTPException(404, "No student results found")

    # Determine question columns
    max_questions = max((len(s["questions"]) for s in students), default=0)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = ["Roll No", "Name"]
    for i in range(1, max_questions + 1):
        header.append(f"Q{i} Marks")
    header += ["Total", "Percentage", "Grade"]
    writer.writerow(header)

    for s in students:
        row = [s["roll_number"], s["name"]]
        q_marks = {q["q_number"]: q["awarded_marks"] for q in s["questions"]}
        for i in range(1, max_questions + 1):
            row.append(q_marks.get(i, ""))
        row += [s["total"], s["percentage"], s["grade"]]
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=exam_{exam_id}_results.csv"}
    )


@app.get("/exam/{exam_id}/export/json")
def export_json(exam_id: int, db: Session = Depends(get_session)):
    results = _compute_results(exam_id, db)
    if not results:
        raise HTTPException(404, "No results found")

    content = json.dumps(results, indent=2, default=str)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=exam_{exam_id}_results.json"}
    )


@app.get("/exam/{exam_id}/export/pdf")
def export_class_pdf(exam_id: int, db: Session = Depends(get_session)):
    results = _compute_results(exam_id, db)
    if not results:
        raise HTTPException(404, "No results found")

    report_dir = EXAM_DB / str(exam_id) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / "class_report.pdf"

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                 fontSize=20, textColor=colors.HexColor('#0F2D5E'),
                                 spaceAfter=10)
    story.append(Paragraph(f"Class Report — {results['exam_name']}", title_style))
    story.append(Paragraph(f"Date: {results['exam_date']} | Total Marks: {results['total_marks']}", styles['Normal']))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#14B8A6')))
    story.append(Spacer(1, 0.3*cm))

    # Stats table
    cs = results["class_stats"]
    stats_data = [
        ["Metric", "Value"],
        ["Total Students", str(cs["total_students"])],
        ["Mean Score", f"{cs['mean']}"],
        ["Median Score", f"{cs['median']}"],
        ["Std Deviation", f"{cs['std_dev']}"],
        ["Pass Rate", f"{cs['pass_rate']}%"],
    ]
    st = Table(stats_data, colWidths=[8*cm, 8*cm])
    st.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F2D5E')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F0F9FF'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.5*cm))

    # Student scores table
    story.append(Paragraph("Student Scores", styles['Heading2']))
    score_data = [["Rank", "Roll No", "Name", "Total", "Percentage", "Grade"]]
    for s in results["students"]:
        score_data.append([
            str(s["rank"]), s["roll_number"], s["name"],
            str(s["total"]), f"{s['percentage']}%", s["grade"]
        ])

    stu_table = Table(score_data, colWidths=[2*cm, 4*cm, 6*cm, 3*cm, 3*cm, 2*cm])
    stu_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F2D5E')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F8FAFC'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(stu_table)

    doc.build(story)
    return FileResponse(str(pdf_path), filename=f"exam_{exam_id}_class_report.pdf",
                        media_type="application/pdf")


@app.get("/exam/{exam_id}/student/{roll_no}/report/pdf")
def export_student_pdf(exam_id: int, roll_no: str, db: Session = Depends(get_session)):
    student = db.exec(select(Student).where(Student.roll_number == roll_no)).first()
    if not student:
        raise HTTPException(404, "Student not found")

    results = _compute_results(exam_id, db)
    if not results:
        raise HTTPException(404, "Exam results not found")

    student_data = next((s for s in results["students"] if s["roll_number"] == roll_no), None)
    if not student_data:
        raise HTTPException(404, "No results for this student")

    report_dir = EXAM_DB / str(exam_id) / "reports" / "students"
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / f"{roll_no}_report.pdf"

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                 fontSize=18, textColor=colors.HexColor('#0F2D5E'))
    story.append(Paragraph(f"Student Report — {results['exam_name']}", title_style))
    story.append(Spacer(1, 0.3*cm))

    # Summary
    summary_data = [
        ["Roll No", roll_no, "Name", student.name],
        ["Total Score", f"{student_data['total']} / {results['total_marks']}",
         "Grade", student_data["grade"]],
        ["Percentage", f"{student_data['percentage']}%",
         "Rank", f"{student_data['rank']} of {results['class_stats']['total_students']}"],
    ]
    sum_table = Table(summary_data, colWidths=[4*cm, 4*cm, 4*cm, 4*cm])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#E0E7FF')),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#E0E7FF')),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 0.5*cm))

    # Per-question breakdown
    story.append(Paragraph("Question Breakdown", styles['Heading2']))
    q_data = [["Q#", "Max", "Awarded", "AI Feedback"]]
    for q in student_data["questions"]:
        q_data.append([
            f"Q{q['q_number']}",
            str(q["max_marks"]),
            str(q["awarded_marks"]) + (" (override)" if q["overridden"] else ""),
            (q["ai_feedback"] or "")[:120],
        ])

    q_table = Table(q_data, colWidths=[2*cm, 2.5*cm, 3*cm, 12.5*cm])
    q_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F2D5E')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F8FAFC'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('WORDWRAP', (3,1), (3,-1), True),
    ]))
    story.append(q_table)

    doc.build(story)
    return FileResponse(str(pdf_path), filename=f"{roll_no}_{results['exam_name']}_report.pdf",
                        media_type="application/pdf")


@app.post("/exam/{exam_id}/student/{roll_no}/override")
def override_marks(
    exam_id: int,
    roll_no: str,
    q_number: int = Form(...),
    new_marks: float = Form(...),
    reason: str = Form(...),
    db: Session = Depends(get_session),
):
    student = db.exec(select(Student).where(Student.roll_number == roll_no)).first()
    if not student:
        raise HTTPException(404, "Student not found")

    question = db.exec(
        select(ExamQuestion).where(
            ExamQuestion.exam_id == exam_id,
            ExamQuestion.q_number == q_number
        )
    ).first()
    if not question:
        raise HTTPException(404, "Question not found")

    answer = db.exec(
        select(StudentAnswer).where(
            StudentAnswer.exam_id == exam_id,
            StudentAnswer.student_id == student.id,
            StudentAnswer.question_id == question.id,
        )
    ).first()
    if not answer:
        raise HTTPException(404, "Answer record not found")

    if new_marks < 0 or new_marks > question.max_marks:
        raise HTTPException(400, f"Marks must be between 0 and {question.max_marks}")

    answer.professor_override = new_marks
    answer.override_reason = reason
    db.add(answer)

    # Audit log
    db.add(AuditLog(
        action="mark_override",
        actor_type="professor",
        actor_id=0,  # No auth context here; actual prof ID passed by caller
        target_type="student_answer",
        target_id=answer.id,
        detail=json.dumps({"exam_id": exam_id, "roll_no": roll_no, "q_number": q_number,
                           "new_marks": new_marks, "reason": reason}),
    ))
    db.commit()

    # Compute new total
    all_answers = db.exec(
        select(StudentAnswer).where(
            StudentAnswer.exam_id == exam_id,
            StudentAnswer.student_id == student.id,
        )
    ).all()
    new_total = sum(
        (a.professor_override if a.professor_override is not None else a.awarded_marks)
        for a in all_answers
    )

    return {"updated": True, "new_total": round(new_total, 2), "q_number": q_number, "new_marks": new_marks}
