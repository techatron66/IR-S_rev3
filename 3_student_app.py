import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
import requests
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")
PROF_SERVER = os.getenv("PROF_SERVER", "http://127.0.0.1:8000")

@app.get("/")
def login(request: Request, cid: str = ""):
    return templates.TemplateResponse(request, name="student_login.html", context={"cid": cid})

@app.post("/verify")
def verify(class_id: str = Form(...), roll_number: str = Form(...), file: UploadFile = File(...)):
    try:
        files = {'file': (file.filename, file.file, file.content_type)}
        resp = requests.post(f"{PROF_SERVER}/verify-student-proxy", files=files, data={'class_id': class_id, 'roll_number': roll_number})
        return resp.json()
    except Exception as e:
        return {"match": False, "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)