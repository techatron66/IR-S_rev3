import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import requests
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")
PROF_SERVER = os.getenv("PROF_SERVER", "http://127.0.0.1:8000")

# ── EXISTING: QR check-in ──────────────────────────────────────────────────

@app.get("/")
def login(request: Request, cid: str = ""):
    return templates.TemplateResponse(request, name="student_login.html", context={"cid": cid})

@app.post("/verify")
def verify(class_id: str = Form(...), roll_number: str = Form(...), file: UploadFile = File(...)):
    try:
        files = {'file': (file.filename, file.file, file.content_type)}
        resp = requests.post(f"{PROF_SERVER}/verify-student-proxy", files=files,
                             data={'class_id': class_id, 'roll_number': roll_number})
        return resp.json()
    except Exception as e:
        return {"match": False, "error": str(e)}

# ── NEW: Student Dashboard ─────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def student_dashboard(request: Request, roll: str = "", class_id: str = ""):
    if not roll or not class_id:
        return templates.TemplateResponse(request, name="student_login.html",
                                          context={"cid": class_id, "error": "Please verify first."})
    try:
        resp = requests.get(f"{PROF_SERVER}/api/student-results/{roll}/{class_id}", timeout=15)
        data = resp.json() if resp.status_code == 200 else {"error": "Not found", "exams": [], "attendance": {}, "student": {"roll": roll, "name": ""}}
    except Exception as e:
        data = {"error": str(e), "exams": [], "attendance": {}, "student": {"roll": roll, "name": ""}}
    return templates.TemplateResponse(request, name="student_dashboard.html",
                                      context={"data": data, "roll": roll, "class_id": class_id})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
