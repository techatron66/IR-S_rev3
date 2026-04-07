import uvicorn
import json
import asyncio
import io
import base64
import os
import re
import csv
import requests
import pandas as pd
import httpx
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from io import StringIO

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Professor, ClassRoom, Student, Attendance,
    Exam, ExamQuestion, StudentAnswer, GradingJob
)
from grading_utils import ocr_pdf_to_text, extract_questions_from_text, grade_student_sheet
# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STUDENT_DB = os.path.join(BASE_DIR, "student_db")
PROF_DB = os.path.join(BASE_DIR, "prof_db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
EXAM_DIR = os.path.join(BASE_DIR, "exam_db")
DATABASE_URL = "sqlite:///./main_app.db"
GPU_URL = "http://127.0.0.1:8001"
STUDENT_URL = os.getenv("STUDENT_URL", "http://192.168.1.6:8002")

# NV API
NV_API_KEY = os.getenv("NV_API_KEY", "")
NV_API_BASE = os.getenv("NV_API_BASE", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2-5")
VISION_MODEL = os.getenv("VISION_MODEL", "meta/llama-3.2-90b-vision-instruct")

GRADING_SYSTEM_PROMPT = """You are an expert academic examiner. Evaluate the student's answer against the reference answer and question.

Score rules:
- 1.0 = complete, accurate, well-articulated
- 0.7 = mostly correct, minor gaps
- 0.5 = partially correct, missing key concepts
- 0.2 = minimal relevant content
- 0.0 = incorrect or off-topic

Consider conceptual understanding over keyword matching. Accept valid alternative explanations.

Return ONLY valid JSON (no markdown, no preamble):
{
  "correlation_score": <float 0.0-1.0>,
  "awarded_marks": <float>,
  "rationale": "<one sentence>",
  "feedback": "<1-2 sentence constructive feedback for the student>",
  "missing_concepts": ["<concept1>", "<concept2>"]
}"""

engine = create_engine(DATABASE_URL)
templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(STUDENT_DB, exist_ok=True)
    os.makedirs(PROF_DB, exist_ok=True)
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(EXAM_DIR, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- AUTH HELPER ---
def get_session():
    with Session(engine) as session:
        yield session


def get_current_prof(request: Request, session: Session = Depends(get_session)):
    prof_id = request.cookies.get("prof_id")
    if not prof_id:
        return None
    return session.get(Professor, int(prof_id))


# =============================================
# LOGIN / REGISTER
# =============================================

@app.get("/", response_class=RedirectResponse)
def root(): return RedirectResponse("/login")


@app.get("/login")
def login_page(request: Request, success: str = None):
    msg = "Registration Successful! Please Login." if success else None
    return templates.TemplateResponse(request, name="login.html", context={"success_msg": msg})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          session: Session = Depends(get_session)):
    prof = session.exec(select(Professor).where(Professor.username == username)).first()
    if not prof:
        return templates.TemplateResponse(request, name="login.html", context={"error": "User does not exist."})
    if prof.password != password:
        return templates.TemplateResponse(request, name="login.html", context={"error": "Incorrect Password"})

    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("prof_id", str(prof.id))
    return resp


@app.get("/register")
def reg_page(request: Request, error: str = None):
    msg = "Username already taken" if error == "Exists" else None
    return templates.TemplateResponse(request, name="register.html", context={"error": msg})


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    existing = session.exec(select(Professor).where(Professor.username == username)).first()
    if existing: return RedirectResponse("/register?error=Exists", status_code=303)

    try:
        session.add(Professor(username=username, password=password))
        session.commit()
        return RedirectResponse("/login?success=1", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/register?error={str(e)}", status_code=303)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("prof_id")
    return resp


# =============================================
# VIEW 1: ATTENDANCE DASHBOARD
# =============================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, class_id: int = None, prof: Professor = Depends(get_current_prof),
              session: Session = Depends(get_session)):
    if not prof: return RedirectResponse("/login")

    classes = prof.classes
    selected_class = session.get(ClassRoom, class_id) if class_id else None
    attendance_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    if selected_class and selected_class.professor_id == prof.id:
        students = selected_class.students
        recs = session.exec(
            select(Attendance).where(Attendance.classroom_id == class_id, Attendance.date == today)).all()

        selfie_ids = {r.student_id for r in recs if r.method == "Selfie"}
        photo_ids = {r.student_id for r in recs if r.method == "ClassPhoto"}
        manual_ids = {r.student_id for r in recs if r.method == "Manual"}

        for s in students:
            status = "Absent"
            method = "-"
            alert = ""
            if s.id in selfie_ids:
                status, method = "Present", "Selfie"
            elif s.id in photo_ids:
                status, method = "Present", "ClassPhoto"
            elif s.id in manual_ids:
                status, method = "Present", "Manual"

            if s.id in selfie_ids and s.id not in photo_ids: alert = "⚠️ SUSPECT: Not in Photo"
            if s.id in photo_ids and s.id not in selfie_ids:
                status = "Present"
                method = "ClassPhoto"
                alert = "⚠️ Present (Photo), No QR"

            attendance_data.append(
                {"roll": s.roll_number, "name": s.name, "status": status, "method": method, "alert": alert})

    return templates.TemplateResponse(request, name="attendance.html", context={
        "prof": prof, "classes": classes,
        "selected_class": selected_class, "attendance": attendance_data,
        "today": today, "student_url": STUDENT_URL
    })


# =============================================
# VIEW 2: MANAGEMENT DASHBOARD
# =============================================

@app.get("/manage", response_class=HTMLResponse)
def manage(request: Request, class_id: int = None, prof: Professor = Depends(get_current_prof),
           session: Session = Depends(get_session)):
    if not prof: return RedirectResponse("/login")

    classes = prof.classes
    selected_class = session.get(ClassRoom, class_id) if class_id else None

    return templates.TemplateResponse(request, name="manage.html", context={
        "prof": prof, "classes": classes,
        "selected_class": selected_class
    })


# =============================================
# ACTIONS (existing v1)
# =============================================

@app.post("/add-class")
def add_class(name: str = Form(...), batch: str = Form(...), prof: Professor = Depends(get_current_prof),
              session: Session = Depends(get_session)):
    new_class = ClassRoom(name=name, batch=batch, professor_id=prof.id)
    session.add(new_class)
    session.commit()

    cls_folder = f"{name}_{batch}".replace(" ", "_")
    os.makedirs(os.path.join(STUDENT_DB, cls_folder), exist_ok=True)
    os.makedirs(os.path.join(PROF_DB, f"prof_{prof.id}", cls_folder), exist_ok=True)

    return RedirectResponse("/manage", status_code=303)


@app.post("/add-student")
async def add_student(class_id: int = Form(...), name: str = Form(...), roll: str = Form(...),
                      files: list[UploadFile] = File(...), session: Session = Depends(get_session)):
    cls = session.get(ClassRoom, class_id)
    cls_folder_name = f"{cls.name}_{cls.batch}".replace(" ", "_")
    stu_folder_name = f"stu_{roll}"
    save_path = os.path.join(STUDENT_DB, cls_folder_name, stu_folder_name)
    os.makedirs(save_path, exist_ok=True)

    for file in files:
        with open(os.path.join(save_path, file.filename), "wb") as f:
            f.write(await file.read())

    session.add(Student(roll_number=roll, name=name, classroom_id=class_id, folder_path=save_path))
    session.commit()
    return RedirectResponse(f"/manage?class_id={class_id}", status_code=303)


@app.post("/process-class-photo")
async def process_photo(class_id: int = Form(...), file: UploadFile = File(...),
                        prof: Professor = Depends(get_current_prof), session: Session = Depends(get_session)):
    cls = session.get(ClassRoom, class_id)
    temp_path = "temp_class_photo.jpg"
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    cls_folder = f"{cls.name}_{cls.batch}".replace(" ", "_")
    target_dir = os.path.join(STUDENT_DB, cls_folder)

    try:
        resp = requests.post(f"{GPU_URL}/process-class-photo", files={'file': open(temp_path, 'rb')},
                             data={'class_folder_path': target_dir})
        found_rolls = resp.json().get("found", [])

        today = datetime.now().strftime("%Y-%m-%d")
        for roll in found_rolls:
            stu = session.exec(
                select(Student).where(Student.classroom_id == class_id, Student.roll_number == roll)).first()
            if stu:
                session.add(Attendance(date=today, time="--", method="ClassPhoto", status="Present",
                                       student_id=stu.id, classroom_id=class_id))
        session.commit()
    except Exception as e:
        print(f"GPU Error: {e}")

    return RedirectResponse(f"/dashboard?class_id={class_id}", status_code=303)


@app.post("/toggle-attendance")
async def toggle_attendance(class_id: int = Form(...), roll: str = Form(...), session: Session = Depends(get_session)):
    stu = session.exec(select(Student).where(Student.classroom_id == class_id, Student.roll_number == roll)).first()
    if not stu: return {"status": "error"}
    today = datetime.now().strftime("%Y-%m-%d")
    existing = session.exec(select(Attendance).where(Attendance.student_id == stu.id, Attendance.date == today)).first()

    if existing:
        session.delete(existing)
        session.commit()
        return {"status": "Absent", "color": "#c62828"}
    else:
        session.add(Attendance(date=today, time="--", method="Manual", status="Present", student_id=stu.id,
                               classroom_id=class_id))
        session.commit()
        return {"status": "Present", "color": "#2e7d32"}


@app.get("/download-csv/{class_id}")
def download_csv(class_id: int, prof: Professor = Depends(get_current_prof), session: Session = Depends(get_session)):
    cls = session.get(ClassRoom, class_id)
    today = datetime.now().strftime("%Y-%m-%d")
    cls_folder = f"{cls.name}_{cls.batch}".replace(" ", "_")
    save_dir = os.path.join(PROF_DB, f"prof_{prof.id}", cls_folder)
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, f"attendance_{today}.csv")

    recs = session.exec(select(Attendance).where(Attendance.classroom_id == class_id, Attendance.date == today)).all()
    students = session.exec(select(Student).where(Student.classroom_id == class_id)).all()

    selfie_ids = {r.student_id for r in recs if r.method == "Selfie"}
    photo_ids = {r.student_id for r in recs if r.method == "ClassPhoto"}
    manual_ids = {r.student_id for r in recs if r.method == "Manual"}

    data = []
    for s in students:
        status, check = "Absent", "OK"
        if s.id in selfie_ids or s.id in photo_ids or s.id in manual_ids: status = "Present"
        if s.id in selfie_ids and s.id not in photo_ids: check = "SUSPECT (No Face in Photo)"
        data.append([s.roll_number, s.name, status, check])

    df = pd.DataFrame(data, columns=["Roll", "Name", "Status", "Verification"])
    df.to_csv(file_path, index=False)
    return FileResponse(file_path, filename=f"attendance_{today}.csv")


@app.get("/api/live-attendance/{class_id}")
def get_live_attendance(class_id: int, session: Session = Depends(get_session)):
    today = datetime.now().strftime("%Y-%m-%d")
    recs = session.exec(select(Attendance).where(Attendance.classroom_id == class_id, Attendance.date == today)).all()
    students = session.exec(select(Student).where(Student.classroom_id == class_id)).all()

    present_ids = {r.student_id for r in recs}
    selfie_ids = {r.student_id for r in recs if r.method == "Selfie"}
    photo_ids = {r.student_id for r in recs if r.method == "ClassPhoto"}

    data = []
    for s in students:
        status, method, alert, color, is_present = "Absent", "-", "", "#c62828", False
        if s.id in present_ids:
            status, color, is_present = "Present", "#2e7d32", True
            rec = next(r for r in recs if r.student_id == s.id)
            method = rec.method

        if s.id in selfie_ids and s.id not in photo_ids: alert = "⚠️ SUSPECT: Not in Photo"
        if s.id in photo_ids and s.id not in selfie_ids:
            status, method, alert, color, is_present = "Present", "ClassPhoto", "⚠️ Present (Photo), No QR", "#2e7d32", True

        data.append({"roll": s.roll_number, "status": status, "method": method, "alert": alert, "color": color,
                     "is_present": is_present})
    return data


@app.post("/verify-student-proxy")
async def verify_proxy(file: UploadFile = File(...), class_id: int = Form(...), roll_number: str = Form(...)):
    with Session(engine) as session:
        stu = session.exec(
            select(Student).where(Student.classroom_id == class_id, Student.roll_number == roll_number)).first()
        if not stu: return {"match": False, "error": "Student not found"}
        try:
            files = {'file': (file.filename, file.file, file.content_type)}
            resp = requests.post(f"{GPU_URL}/verify-selfie", files=files,
                                 data={'student_folder_path': stu.folder_path})
            if resp.json().get("match"):
                session.add(
                    Attendance(date=datetime.now().strftime("%Y-%m-%d"), time=datetime.now().strftime("%H:%M"),
                               method="Selfie", status="Present", student_id=stu.id, classroom_id=class_id))
                session.commit()
                return {"match": True}
        except:
            pass
        return {"match": False}



# =============================================
# GRADING FEATURE ROUTES
# =============================================

@app.get("/grading", response_class=HTMLResponse)
def grading_page(request: Request, class_id: int = None,
                 prof: Professor = Depends(get_current_prof),
                 session: Session = Depends(get_session)):
    if not prof:
        return RedirectResponse("/login")
    classes = prof.classes
    selected_class = session.get(ClassRoom, class_id) if class_id else None
    exams = []
    if selected_class and selected_class.professor_id == prof.id:
        exams = session.exec(
            select(Exam).where(Exam.classroom_id == class_id)
        ).all()
        for exam in exams:
            job = session.exec(
                select(GradingJob).where(GradingJob.exam_id == exam.id)
            ).first()
            exam._job = job
    return templates.TemplateResponse(request, name="grading.html", context={
        "prof": prof,
        "classes": classes,
        "selected_class": selected_class,
        "selected_class_id": class_id,
        "exams": exams
    })

@app.post("/grading/upload-question-paper")
async def upload_question_paper(
    class_id: int = Form(...),
    exam_name: str = Form(...),
    exam_date: str = Form(...),
    question_paper: UploadFile = File(...),
    prof: Professor = Depends(get_current_prof),
    session: Session = Depends(get_session)
):
    if not prof:
        return RedirectResponse("/login")
    
    exam = Exam(
        classroom_id=class_id,
        professor_id=prof.id,
        name=exam_name,
        exam_date=exam_date,
        status="draft",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    session.add(exam)
    session.commit()
    session.refresh(exam)
    
    os.makedirs(EXAM_DIR, exist_ok=True)
    exam_folder = os.path.join(EXAM_DIR, str(exam.id))
    os.makedirs(exam_folder, exist_ok=True)
    
    _, ext = os.path.splitext(question_paper.filename)
    qp_path = os.path.join(exam_folder, f"question_paper{ext}")
    pdf_bytes = await question_paper.read()
    with open(qp_path, "wb") as f:
        f.write(pdf_bytes)
        
    raw_text = await ocr_pdf_to_text(pdf_bytes)
    extracted_questions = await extract_questions_from_text(raw_text)
    
    return templates.TemplateResponse(request=None, name="grading_confirm.html", context={
        "request": {},
        "exam": exam,
        "extracted_questions": extracted_questions,
        "class_id": class_id
    })

@app.post("/grading/confirm-questions")
async def confirm_questions(
    exam_id: int = Form(...),
    q_texts: list[str] = Form(...),
    q_marks: list[float] = Form(...),
    q_refs: list[str] = Form(...),
    answer_sheets: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    prof: Professor = Depends(get_current_prof),
    session: Session = Depends(get_session)
):
    if not prof:
        return RedirectResponse("/login")
        
    exam = session.get(Exam, exam_id)
    if not exam:
        return RedirectResponse("/grading")

    for i, (text, marks, ref) in enumerate(zip(q_texts, q_marks, q_refs)):
        if not text.strip(): continue
        q = ExamQuestion(
            exam_id=exam.id,
            q_number=i+1,
            question_text=text.strip(),
            max_marks=float(marks),
            reference_answer=ref.strip() if ref.strip() else None
        )
        session.add(q)
    session.commit()
    
    sheet_data = []
    for sheet in answer_sheets:
        if not sheet.filename: continue
        roll = os.path.splitext(sheet.filename)[0]
        data = await sheet.read()
        sheet_data.append((roll, data))
        
    job = GradingJob(exam_id=exam.id, status="queued", total_sheets=len(sheet_data))
    exam.status = "grading"
    session.add(job)
    session.add(exam)
    session.commit()
    session.refresh(job)
    
    background_tasks.add_task(_run_grading_job, job.id, exam.id, sheet_data)
    return RedirectResponse(f"/grading?class_id={exam.classroom_id}", status_code=303)

async def _run_grading_job(job_id: int, exam_id: int, sheet_data: list[tuple[str, bytes]]):
    from sqlmodel import Session, select, create_engine
    engine2 = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    
    with Session(engine2) as s:
        job = s.get(GradingJob, job_id)
        exam = s.get(Exam, exam_id)
        questions = s.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
        job.status = "processing"
        s.add(job)
        s.commit()

    errors = []
    for roll_number, pdf_bytes in sheet_data:
        try:
            results = await grade_student_sheet(pdf_bytes, questions, roll_number)
            with Session(engine2) as s:
                student = s.exec(
                    select(Student).where(Student.classroom_id == exam.classroom_id,
                                          Student.roll_number == roll_number)
                ).first()
                if not student:
                    errors.append(f"{roll_number}: not found in class")
                    continue
                    
                old = s.exec(select(StudentAnswer).where(
                    StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == student.id)).all()
                for a in old: s.delete(a)
                
                for r in results:
                    s.add(StudentAnswer(
                        exam_id=exam_id, question_id=r["question_id"], student_id=student.id,
                        raw_answer_text=r["raw_answer_text"][:3000],
                        closeness_pct=r["closeness_pct"], awarded_marks=r["awarded_marks"],
                        ai_feedback=r["feedback"]
                    ))
                s.commit()
        except Exception as e:
            errors.append(f"{roll_number}: {str(e)[:200]}")
        finally:
            with Session(engine2) as s:
                j = s.get(GradingJob, job_id)
                j.processed_sheets += 1
                s.add(j)
                s.commit()

    with Session(engine2) as s:
        j = s.get(GradingJob, job_id)
        ex = s.get(Exam, exam_id)
        j.status = "failed" if len(errors) == len(sheet_data) else "completed"
        j.error_log = "\n".join(errors) if errors else None
        ex.status = "published"
        s.add(j)
        s.add(ex)
        s.commit()

@app.get("/api/grading/job/{exam_id}")
def get_grading_job(exam_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(GradingJob).where(GradingJob.exam_id == exam_id)).first()
    if not job:
        return JSONResponse({"status": "not_found", "progress": 0, "processed": 0, "total": 0})
    pct = int((job.processed_sheets / max(1, job.total_sheets)) * 100) if job.total_sheets > 0 else 0
    return JSONResponse({
        "status": job.status,
        "progress": pct,
        "processed": job.processed_sheets,
        "total": job.total_sheets,
        "error_log": job.error_log
    })

@app.get("/grading/results/{exam_id}", response_class=HTMLResponse)
def grading_results(request: Request, exam_id: int,
                    prof: Professor = Depends(get_current_prof),
                    session: Session = Depends(get_session)):
    if not prof:
        return RedirectResponse("/login")
    exam = session.get(Exam, exam_id)
    if not exam or exam.professor_id != prof.id:
        return RedirectResponse("/grading")
    questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    students = session.exec(select(Student).where(Student.classroom_id == exam.classroom_id)).all()
    
    results = []
    for s in students:
        answers = session.exec(select(StudentAnswer).where(
            StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == s.id)).all()
        ans_map = {a.question_id: a for a in answers}
        breakdown = []
        total = 0.0
        max_total = sum(q.max_marks for q in questions)
        for q in questions:
            a = ans_map.get(q.id)
            if a:
                awarded = a.professor_override if a.professor_override is not None else a.awarded_marks
                breakdown.append({
                    "q_number": q.q_number,
                    "question_text": q.question_text,
                    "max_marks": q.max_marks,
                    "awarded": awarded,
                    "closeness_pct": a.closeness_pct,
                    "feedback": a.ai_feedback,
                    "answer_id": a.id,
                    "overridden": a.professor_override is not None
                })
                total += awarded
            else:
                breakdown.append({
                    "q_number": q.q_number,
                    "question_text": q.question_text,
                    "max_marks": q.max_marks,
                    "awarded": 0.0,
                    "closeness_pct": 0.0,
                    "feedback": "Not graded",
                    "answer_id": None,
                    "overridden": False
                })
        results.append({
            "roll": s.roll_number,
            "name": s.name,
            "student_id": s.id,
            "total": round(total, 2),
            "max_total": max_total,
            "percentage": round((total / max(0.001, max_total)) * 100, 1),
            "breakdown": breakdown
        })
        
    results.sort(key=lambda x: x["total"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
        
    scores = [r["total"] for r in results if r["total"] > 0]
    stats = {}
    if scores:
        stats = {
            "mean": round(sum(scores) / len(scores), 2),
            "highest": max(scores),
            "lowest": min(scores),
            "pass_count": sum(1 for s in scores if s >= 0.4 * results[0]["max_total"]) if results else 0,
            "total_students": len(students)
        }
    classroom = session.get(ClassRoom, exam.classroom_id)
    return templates.TemplateResponse(request, name="grading_results.html", context={
        "prof": prof, "exam": exam, "classroom": classroom, "questions": questions, "results": results, "stats": stats
    })

@app.post("/api/grading/override")
async def override_mark(
    answer_id: int = Form(...),
    new_marks: float = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
    prof: Professor = Depends(get_current_prof)
):
    if not prof: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    answer = session.get(StudentAnswer, answer_id)
    if not answer: return JSONResponse({"error": "Answer not found"}, status_code=404)
    q = session.get(ExamQuestion, answer.question_id)
    new_m = max(0.0, min(float(new_marks), q.max_marks))
    answer.professor_override = new_m
    answer.override_reason = reason
    session.add(answer)
    session.commit()
    return JSONResponse({"ok": True, "new_marks": new_m})

@app.get("/grading/export/{exam_id}/csv")
def export_results_csv(exam_id: int, prof: Professor = Depends(get_current_prof), session: Session = Depends(get_session)):
    if not prof: return RedirectResponse("/login")
    exam = session.get(Exam, exam_id)
    questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    students = session.exec(select(Student).where(Student.classroom_id == exam.classroom_id)).all()
    
    output = StringIO()
    writer = csv.writer(output)
    header = ["Roll No", "Name", "Total", "Max Total", "Percentage"] + [f"Q{q.q_number} ({q.max_marks})" for q in questions]
    writer.writerow(header)
    
    for s in students:
        answers = session.exec(select(StudentAnswer).where(StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == s.id)).all()
        ans_map = {a.question_id: a for a in answers}
        row = [s.roll_number, s.name]
        total = 0.0
        max_total = sum(q.max_marks for q in questions)
        per_q = []
        for q in questions:
            a = ans_map.get(q.id)
            awarded = a.professor_override if (a and a.professor_override is not None) else (a.awarded_marks if a else 0.0)
            total += awarded
            per_q.append(round(awarded, 2))
        row += [round(total, 2), max_total, round((total / max(0.001, max_total)) * 100, 1)] + per_q
        writer.writerow(row)
        
    output.seek(0)
    csv_path = os.path.join(EXAM_DIR, f"{exam.name.replace(' ', '_')}_results.csv")
    with open(csv_path, "w") as f: f.write(output.getvalue())
    return FileResponse(csv_path, filename=f"{exam.name}_results.csv", media_type="text/csv")

@app.get("/api/student-results/{roll_number}/{class_id}")
def get_student_results_api(roll_number: str, class_id: int, session: Session = Depends(get_session)):
    student = session.exec(select(Student).where(
        Student.classroom_id == class_id, Student.roll_number == roll_number)).first()
    if not student: return JSONResponse({"error": "Student not found"}, status_code=404)
    
    exams = session.exec(select(Exam).where(Exam.classroom_id == class_id, Exam.status == "published")).all()
    results = []
    
    for exam in exams:
        questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)).all()
        answers = session.exec(select(StudentAnswer).where(
            StudentAnswer.exam_id == exam.id, StudentAnswer.student_id == student.id)).all()
        ans_map = {a.question_id: a for a in answers}
        max_total = sum(q.max_marks for q in questions)
        breakdown = []
        total = 0.0
        for q in questions:
            a = ans_map.get(q.id)
            awarded = a.professor_override if (a and a.professor_override is not None) else (a.awarded_marks if a else 0.0)
            feedback = a.ai_feedback if a else "Not graded yet"
            total += awarded
            breakdown.append({
                "q_number": q.q_number, "question_text": q.question_text,
                "max_marks": q.max_marks, "awarded": round(awarded, 2),
                "closeness_pct": a.closeness_pct if a else 0.0,
                "feedback": feedback
            })
            
        all_ans = session.exec(select(StudentAnswer).where(StudentAnswer.exam_id == exam.id)).all()
        if all_ans:
            by_student = {}
            for a in all_ans:
                aw = a.professor_override if a.professor_override is not None else a.awarded_marks
                by_student[a.student_id] = by_student.get(a.student_id, 0) + aw
            class_avg = round(sum(by_student.values()) / len(by_student), 2) if by_student else 0.0
            sorted_scores = sorted(by_student.values(), reverse=True)
            rank = sorted_scores.index(by_student.get(student.id, 0)) + 1 if student.id in by_student else None
        else:
            class_avg = 0.0
            rank = None
            
        results.append({
            "exam_id": exam.id, "exam_name": exam.name, "exam_date": exam.exam_date,
            "total": round(total, 2), "max_total": max_total,
            "percentage": round((total / max(0.001, max_total)) * 100, 1),
            "class_average": class_avg, "rank": rank, "breakdown": breakdown
        })
        
    all_att = session.exec(select(Attendance).where(
        Attendance.classroom_id == class_id, Attendance.student_id == student.id)).all()
    total_days = len(set(a.date for a in all_att)) if all_att else 0
    present_days = sum(1 for a in all_att if a.status == "Present") if all_att else 0
    
    return JSONResponse({
        "student": {"roll": student.roll_number, "name": student.name},
        "attendance": {
            "total_sessions": total_days,
            "present": present_days,
            "percentage": round((present_days / max(1, total_days)) * 100, 1) if total_days > 0 else 0.0
        },
        "exams": results
    })

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    uvicorn.run(app, host="0.0.0.0", port=8000)
