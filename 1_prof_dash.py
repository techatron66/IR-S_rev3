import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Session, create_engine, select
from models import Professor, ClassRoom, Student, Attendance
import os
import requests
import pandas as pd
from datetime import datetime
from contextlib import asynccontextmanager

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STUDENT_DB = os.path.join(BASE_DIR, "student_db")
PROF_DB = os.path.join(BASE_DIR, "prof_db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATABASE_URL = f"sqlite:///./main_app.db"  # Updated for Windows safety
GPU_URL = "http://127.0.0.1:8001"
STUDENT_URL = os.getenv("STUDENT_URL", "http://localhost:8002")

engine = create_engine(DATABASE_URL)
templates = Jinja2Templates(directory = "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(STUDENT_DB, exist_ok = True)
    os.makedirs(PROF_DB, exist_ok = True)
    if not os.path.exists(STATIC_DIR):
        os.makedirs(STATIC_DIR)
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(lifespan = lifespan)
app.mount("/static", StaticFiles(directory = STATIC_DIR), name = "static")


# --- AUTH HELPER ---
def get_session():
    with Session(engine) as session:
        yield session


def get_current_prof(request: Request, session: Session = Depends(get_session)):
    prof_id = request.cookies.get("prof_id")
    if not prof_id: return None
    return session.get(Professor, int(prof_id))


# --- LOGIN / REGISTER ---
@app.get("/", response_class = RedirectResponse)
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
    
    resp = RedirectResponse("/dashboard", status_code = 303)
    resp.set_cookie("prof_id", str(prof.id))
    return resp


@app.get("/register")
def reg_page(request: Request, error: str = None):
    msg = "Username already taken" if error == "Exists" else None
    return templates.TemplateResponse(request, name="register.html", context={"error": msg})


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    existing = session.exec(select(Professor).where(Professor.username == username)).first()
    if existing: return RedirectResponse("/register?error=Exists", status_code = 303)
    
    try:
        session.add(Professor(username = username, password = password))
        session.commit()
        return RedirectResponse("/login?success=1", status_code = 303)
    except Exception as e:
        return RedirectResponse(f"/register?error={str(e)}", status_code = 303)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("prof_id")
    return resp


# --- VIEW 1: ATTENDANCE DASHBOARD ---
@app.get("/dashboard", response_class = HTMLResponse)
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
    
    # Renders the ATTENDANCE specific template
    return templates.TemplateResponse(request, name="attendance.html", context={
        "prof": prof, "classes": classes,
        "selected_class": selected_class, "attendance": attendance_data,
        "today": today, "student_url": STUDENT_URL
    })


# --- VIEW 2: MANAGEMENT DASHBOARD ---
@app.get("/manage", response_class = HTMLResponse)
def manage(request: Request, class_id: int = None, prof: Professor = Depends(get_current_prof),
           session: Session = Depends(get_session)):
    if not prof: return RedirectResponse("/login")
    
    classes = prof.classes
    selected_class = session.get(ClassRoom, class_id) if class_id else None
    
    # Renders the MANAGEMENT specific template
    return templates.TemplateResponse(request, name="manage.html", context={
        "prof": prof, "classes": classes,
        "selected_class": selected_class
    })


# --- ACTIONS ---
@app.post("/add-class")
def add_class(name: str = Form(...), batch: str = Form(...), prof: Professor = Depends(get_current_prof),
              session: Session = Depends(get_session)):
    new_class = ClassRoom(name = name, batch = batch, professor_id = prof.id)
    session.add(new_class)
    session.commit()
    
    cls_folder = f"{name}_{batch}".replace(" ", "_")
    os.makedirs(os.path.join(STUDENT_DB, cls_folder), exist_ok = True)
    os.makedirs(os.path.join(PROF_DB, f"prof_{prof.id}", cls_folder), exist_ok = True)
    
    # Redirect back to MANAGE page
    return RedirectResponse("/manage", status_code = 303)


@app.post("/add-student")
async def add_student(class_id: int = Form(...), name: str = Form(...), roll: str = Form(...),
                      files: list[UploadFile] = File(...), session: Session = Depends(get_session)):
    cls = session.get(ClassRoom, class_id)
    cls_folder_name = f"{cls.name}_{cls.batch}".replace(" ", "_")
    stu_folder_name = f"stu_{roll}"
    save_path = os.path.join(STUDENT_DB, cls_folder_name, stu_folder_name)
    os.makedirs(save_path, exist_ok = True)
    
    for file in files:
        with open(os.path.join(save_path, file.filename), "wb") as f:
            f.write(await file.read())
    
    session.add(Student(roll_number = roll, name = name, classroom_id = class_id, folder_path = save_path))
    session.commit()
    # Redirect back to MANAGE page
    return RedirectResponse(f"/manage?class_id={class_id}", status_code = 303)


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
        resp = requests.post(f"{GPU_URL}/process-class-photo", files = {'file': open(temp_path, 'rb')},
                             data = {'class_folder_path': target_dir})
        found_rolls = resp.json().get("found", [])
        
        today = datetime.now().strftime("%Y-%m-%d")
        for roll in found_rolls:
            stu = session.exec(
                select(Student).where(Student.classroom_id == class_id, Student.roll_number == roll)).first()
            if stu:
                session.add(Attendance(date = today, time = "--", method = "ClassPhoto", status = "Present",
                                       student_id = stu.id, classroom_id = class_id))
        session.commit()
    except Exception as e:
        print(f"GPU Error: {e}")
    
    # Redirect to ATTENDANCE page to see results
    return RedirectResponse(f"/dashboard?class_id={class_id}", status_code = 303)


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
        session.add(Attendance(date = today, time = "--", method = "Manual", status = "Present", student_id = stu.id,
                               classroom_id = class_id))
        session.commit()
        return {"status": "Present", "color": "#2e7d32"}


@app.get("/download-csv/{class_id}")
def download_csv(class_id: int, prof: Professor = Depends(get_current_prof), session: Session = Depends(get_session)):
    cls = session.get(ClassRoom, class_id)
    today = datetime.now().strftime("%Y-%m-%d")
    cls_folder = f"{cls.name}_{cls.batch}".replace(" ", "_")
    save_dir = os.path.join(PROF_DB, f"prof_{prof.id}", cls_folder)
    os.makedirs(save_dir, exist_ok = True)
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
    
    df = pd.DataFrame(data, columns = ["Roll", "Name", "Status", "Verification"])
    df.to_csv(file_path, index = False)
    return FileResponse(file_path, filename = f"attendance_{today}.csv")


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
            resp = requests.post(f"{GPU_URL}/verify-selfie", files = files,
                                 data = {'student_folder_path': stu.folder_path})
            if resp.json().get("match"):
                session.add(
                    Attendance(date = datetime.now().strftime("%Y-%m-%d"), time = datetime.now().strftime("%H:%M"),
                               method = "Selfie", status = "Present", student_id = stu.id, classroom_id = class_id))
                session.commit()
                return {"match": True}
        except:
            pass
        return {"match": False}


if __name__ == "__main__":
    uvicorn.run(app, host = "0.0.0.0", port = 8000)