"""
IRIS v2 — Student Portal Service
Port: 8004
JWT auth, attendance view, marks, disputes
"""
import sys
import os

# Add parent directory to python path for running directly from services folder
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, _ROOT)

import json
import re
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI, Depends, HTTPException, Request,
    UploadFile, File, Form, Header
)
from fastapi.responses import (
    FileResponse, HTMLResponse, RedirectResponse, JSONResponse
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from core.config import settings
from core.database import get_session, init_db, engine
from core.models import (
    Student, StudentUser, ClassRoom, Attendance,
    Exam, ExamQuestion, StudentAnswer, Dispute, Notification, AuditLog
)

# ─── Setup ────────────────────────────────────────────────────────────────────

BASE_DIR = _HERE   # services/
PROJECT_ROOT = _ROOT   # project root

DISPUTES_DIR = Path(_ROOT) / "disputes"
DISPUTES_DIR.mkdir(exist_ok=True)

app = FastAPI(title="IRIS Student Portal", version="2.0")
templates = Jinja2Templates(directory=os.path.join(_ROOT, "templates", "student_portal"))
app.mount("/static", StaticFiles(directory=os.path.join(_ROOT, "static")), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@app.on_event("startup")
def startup():
    init_db()


# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=settings.STUDENT_JWT_EXPIRE_HOURS)
    return jwt.encode(payload, settings.STUDENT_JWT_SECRET, algorithm=settings.STUDENT_JWT_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.STUDENT_JWT_SECRET, algorithms=[settings.STUDENT_JWT_ALGO])


def get_current_student(request: Request) -> Optional[StudentUser]:
    token = request.cookies.get("iris_student_token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        with Session(engine) as db:
            return db.exec(
                select(StudentUser).where(StudentUser.roll_no == payload["sub"])
            ).first()
    except JWTError:
        return None


def require_student(request: Request) -> StudentUser:
    student = get_current_student(request)
    if not student:
        raise HTTPException(status_code=302, detail="/login",
                            headers={"Location": "/login"})
    return student


# ─── AUTH ROUTES ──────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
def root(request: Request):
    stu = get_current_student(request)
    if stu:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(
    request: Request,
    roll_no: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    user = db.exec(select(StudentUser).where(StudentUser.roll_no == roll_no)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid roll number or password"},
            status_code=401
        )
    token = create_token({"sub": user.roll_no})
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("iris_student_token", token, httponly=True,
                    max_age=settings.STUDENT_JWT_EXPIRE_HOURS * 3600)
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register")
def register(
    request: Request,
    roll_no: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    existing = db.exec(select(StudentUser).where(StudentUser.roll_no == roll_no)).first()
    if existing:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Roll number already registered."},
            status_code=400
        )
    user = StudentUser(
        roll_no=roll_no,
        name=name,
        password_hash=hash_password(password),
        class_ids="[]"
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/login", status_code=302)


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("iris_student_token")
    return resp


@app.get("/logout")
def logout_get():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("iris_student_token")
    return resp


# ─── ADMIN: STUDENT IMPORT ───────────────────────────────────────────────────

@app.post("/admin/students/import")
async def import_students(
    file: UploadFile = File(...),
    x_internal_key: str = Header(..., alias="X-Internal-Key"),
    db: Session = Depends(get_session),
):
    if x_internal_key != settings.INTERNAL_KEY:
        raise HTTPException(403, "Invalid internal key")

    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    created, skipped, errors = 0, 0, []
    for row in reader:
        try:
            roll_no = row.get("roll_no", "").strip()
            name = row.get("name", "").strip()
            email = row.get("email", "").strip() or None
            password = row.get("password", "iris2025").strip()
            class_ids_raw = row.get("class_ids", "").strip()

            if not roll_no or not name:
                errors.append(f"Missing roll_no or name: {row}")
                continue

            # Parse class_ids (comma-separated ints)
            if class_ids_raw:
                cids = [int(c.strip()) for c in class_ids_raw.split(",") if c.strip().isdigit()]
            else:
                cids = []

            existing = db.exec(select(StudentUser).where(StudentUser.roll_no == roll_no)).first()
            if existing:
                skipped += 1
                continue

            db.add(StudentUser(
                roll_no=roll_no,
                name=name,
                email=email,
                password_hash=hash_password(password),
                class_ids=json.dumps(cids),
            ))
            created += 1
        except Exception as e:
            errors.append(f"Row error: {str(e)} — {row}")

    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# ─── STUDENT PAGES ────────────────────────────────────────────────────────────

def _get_student_classes(user: StudentUser, db: Session) -> list:
    """Return ClassRoom objects for the student's enrolled classes."""
    try:
        cids = json.loads(user.class_ids or "[]")
    except Exception:
        cids = []
    classes = []
    for cid in cids:
        cls = db.get(ClassRoom, cid)
        if cls:
            classes.append(cls)
    return classes


def _get_linked_student(user: StudentUser, db: Session) -> Optional[Student]:
    """Find the Student record linked to this StudentUser by roll_no."""
    return db.exec(
        select(Student).where(Student.roll_number == user.roll_no)
    ).first()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    classes = _get_student_classes(user, db)
    student = _get_linked_student(user, db)

    # Attendance summary
    total_sessions = 0
    attended = 0
    if student:
        for cls in classes:
            all_att = db.exec(
                select(Attendance).where(Attendance.classroom_id == cls.id)
            ).all()
            dates = list({a.date for a in all_att})
            total_sessions += len(dates)
            att_dates = {a.date for a in all_att if a.student_id == student.id}
            attended += len(att_dates)

    attendance_pct = round(attended / total_sessions * 100, 1) if total_sessions else 0.0

    # Exam summary
    exam_count = 0
    for cls in classes:
        exams = db.exec(
            select(Exam).where(Exam.class_id == cls.id, Exam.status == "published")
        ).all()
        exam_count += len(exams)

    # Pending disputes
    pending_disputes = 0
    if user:
        pending_disputes = len(db.exec(
            select(Dispute).where(
                Dispute.student_id == user.id,
                Dispute.status == "pending"
            )
        ).all())

    unread_notifs = len(db.exec(
        select(Notification).where(
            Notification.user_type == "student",
            Notification.user_id == user.id,
            Notification.read == False,
        )
    ).all())

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "classes": classes,
        "attendance_pct": attendance_pct,
        "attended": attended,
        "total_sessions": total_sessions,
        "exam_count": exam_count,
        "pending_disputes": pending_disputes,
        "unread_notifs": unread_notifs,
    })


@app.get("/attendance", response_class=HTMLResponse)
def attendance_page(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    classes = _get_student_classes(user, db)
    student = _get_linked_student(user, db)

    class_data = []
    for cls in classes:
        # Get all unique session dates for this class
        all_att = db.exec(
            select(Attendance).where(Attendance.classroom_id == cls.id)
        ).all()
        session_dates = sorted({a.date for a in all_att})
        total_sessions = len(session_dates)

        # Student's attendance
        if student:
            my_att = {a.date: a for a in all_att if a.student_id == student.id}
        else:
            my_att = {}

        attended = len(my_att)
        pct = round(attended / total_sessions * 100, 1) if total_sessions else 0.0
        at_risk = pct < 75 and total_sessions > 0

        sessions = []
        for date in session_dates:
            att_rec = my_att.get(date)
            sessions.append({
                "date": date,
                "status": "present" if att_rec else "absent",
                "method": att_rec.method if att_rec else "-",
            })

        class_data.append({
            "class": {"id": cls.id, "name": cls.name, "batch": cls.batch},
            "total_sessions": total_sessions,
            "attended": attended,
            "percentage": pct,
            "at_risk": at_risk,
            "sessions": sessions,
        })

    unread_notifs = len(db.exec(
        select(Notification).where(
            Notification.user_type == "student",
            Notification.user_id == user.id,
            Notification.read == False,
        )
    ).all())

    return templates.TemplateResponse(request, "attendance.html", {
        "user": user,
        "class_data": class_data,
        "unread_notifs": unread_notifs,
    })


@app.get("/marks", response_class=HTMLResponse)
def marks_page(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    classes = _get_student_classes(user, db)
    student = _get_linked_student(user, db)

    exam_data = []
    for cls in classes:
        exams = db.exec(
            select(Exam).where(
                Exam.class_id == cls.id,
                Exam.status.in_(["completed", "published"])
            )
        ).all()
        for exam in exams:
            if not student:
                continue

            my_answers = db.exec(
                select(StudentAnswer).where(
                    StudentAnswer.exam_id == exam.id,
                    StudentAnswer.student_id == student.id,
                )
            ).all()
            if not my_answers:
                continue

            my_total = sum(
                (a.professor_override if a.professor_override is not None else a.awarded_marks)
                for a in my_answers
            )

            # Class average
            all_answers = db.exec(
                select(StudentAnswer).where(StudentAnswer.exam_id == exam.id)
            ).all()

            # Group by student
            from collections import defaultdict
            by_stu = defaultdict(float)
            for a in all_answers:
                by_stu[a.student_id] += (a.professor_override if a.professor_override is not None else a.awarded_marks)

            class_totals = list(by_stu.values())
            class_avg = round(sum(class_totals) / len(class_totals), 2) if class_totals else 0.0

            # Rank
            rank = sum(1 for t in class_totals if t > my_total) + 1
            total_students = len(class_totals)

            # Question breakdown
            questions = db.exec(
                select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)
            ).all()
            q_map = {q.id: q for q in questions}

            q_breakdown = []
            for a in sorted(my_answers, key=lambda x: x.question_id):
                q = q_map.get(a.question_id)
                if q:
                    awarded = a.professor_override if a.professor_override is not None else a.awarded_marks
                    q_breakdown.append({
                        "q_number": q.q_number,
                        "max_marks": q.max_marks,
                        "awarded_marks": awarded,
                        "ai_feedback": a.ai_feedback or "",
                        "missing_concepts": json.loads(a.missing_concepts or "[]"),
                        "status": a.status,
                        "overridden": a.professor_override is not None,
                    })

            pct = round(my_total / exam.total_marks * 100, 1) if exam.total_marks else 0.0

            exam_data.append({
                "exam": exam,
                "class_name": cls.name,
                "batch": cls.batch,
                "my_total": round(my_total, 2),
                "percentage": pct,
                "class_avg": class_avg,
                "rank": rank,
                "total_students": total_students,
                "questions": q_breakdown,
            })

    unread_notifs = len(db.exec(
        select(Notification).where(
            Notification.user_type == "student",
            Notification.user_id == user.id,
            Notification.read == False,
        )
    ).all())

    return templates.TemplateResponse(request, "marks.html", {
        "user": user,
        "exam_data": exam_data,
        "unread_notifs": unread_notifs,
    })


@app.get("/disputes", response_class=HTMLResponse)
def disputes_page(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    my_disputes = db.exec(
        select(Dispute).where(Dispute.student_id == user.id)
    ).all()

    # Get classes for dispute form
    classes = _get_student_classes(user, db)

    unread_notifs = len(db.exec(
        select(Notification).where(
            Notification.user_type == "student",
            Notification.user_id == user.id,
            Notification.read == False,
        )
    ).all())

    return templates.TemplateResponse(request, "disputes.html", {
        "user": user,
        "disputes": my_disputes,
        "classes": classes,
        "unread_notifs": unread_notifs,
    })


@app.post("/disputes/new")
async def new_dispute(
    request: Request,
    dispute_type: str = Form(...),
    ref_id: int = Form(...),
    reason: str = Form(...),
    evidence: Optional[UploadFile] = File(None),
    db: Session = Depends(get_session),
):
    user = get_current_student(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    evidence_path = None
    if evidence and evidence.filename:
        ev_dir = DISPUTES_DIR / str(user.id)
        ev_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[^\w\.-]', '_', evidence.filename)
        ev_path = ev_dir / safe_name
        ev_content = await evidence.read()
        if len(ev_content) <= settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            ev_path.write_bytes(ev_content)
            evidence_path = str(ev_path)

    dispute = Dispute(
        student_id=user.id,
        type=dispute_type,
        ref_id=ref_id,
        reason=reason,
        evidence_path=evidence_path,
        status="pending",
    )
    db.add(dispute)
    db.commit()

    return RedirectResponse("/disputes", status_code=302)


@app.get("/notifications")
def get_notifications(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        return JSONResponse({"unread_count": 0, "notifications": []})

    notifs = db.exec(
        select(Notification).where(
            Notification.user_type == "student",
            Notification.user_id == user.id,
        ).order_by(Notification.created_at.desc()).limit(20)
    ).all()

    unread_count = sum(1 for n in notifs if not n.read)
    return {
        "unread_count": unread_count,
        "notifications": [
            {
                "id": n.id,
                "message": n.message,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifs
        ]
    }


@app.post("/notifications/{notif_id}/read")
def mark_read(notif_id: int, request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    notif = db.get(Notification, notif_id)
    if notif and notif.user_id == user.id:
        notif.read = True
        db.add(notif)
        db.commit()
    return {"ok": True}


# ─── API ENDPOINTS FOR AJAX ───────────────────────────────────────────────────

@app.get("/api/attendance/{class_id}")
def api_attendance(class_id: int, request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    student = _get_linked_student(user, db)
    if not student:
        return {"sessions": []}

    all_att = db.exec(
        select(Attendance).where(Attendance.classroom_id == class_id)
    ).all()
    session_dates = sorted({a.date for a in all_att})
    my_att = {a.date: a for a in all_att if a.student_id == student.id}

    sessions = []
    for date in session_dates:
        rec = my_att.get(date)
        sessions.append({
            "date": date,
            "status": "present" if rec else "absent",
            "method": rec.method if rec else "-",
        })

    return {"class_id": class_id, "sessions": sessions}


@app.get("/api/exam/{exam_id}/breakdown")
def api_exam_breakdown(exam_id: int, request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    student = _get_linked_student(user, db)
    if not student:
        return {"questions": []}

    answers = db.exec(
        select(StudentAnswer).where(
            StudentAnswer.exam_id == exam_id,
            StudentAnswer.student_id == student.id,
        )
    ).all()
    questions = db.exec(
        select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
    ).all()
    q_map = {q.id: q for q in questions}

    result = []
    for a in sorted(answers, key=lambda x: x.question_id):
        q = q_map.get(a.question_id)
        if q:
            awarded = a.professor_override if a.professor_override is not None else a.awarded_marks
            result.append({
                "q_number": q.q_number,
                "question_text": q.question_text,
                "max_marks": q.max_marks,
                "awarded_marks": awarded,
                "ai_feedback": a.ai_feedback,
                "missing_concepts": json.loads(a.missing_concepts or "[]"),
                "status": a.status,
            })
    return {"exam_id": exam_id, "questions": result}


@app.get("/api/disputes")
def api_disputes(request: Request, db: Session = Depends(get_session)):
    user = get_current_student(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    disputes = db.exec(
        select(Dispute).where(Dispute.student_id == user.id)
    ).all()
    return {
        "disputes": [
            {
                "id": d.id,
                "type": d.type,
                "ref_id": d.ref_id,
                "reason": d.reason,
                "status": d.status,
                "professor_response": d.professor_response,
                "created_at": d.created_at.isoformat(),
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in disputes
        ]
    }
