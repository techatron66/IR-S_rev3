# IRIS v2 — Skill & Technology Reference
## Engineering Competency Map

---

## 1. Core Stack (Inherited from v1)

| Technology | Role | Key APIs |
|---|---|---|
| **FastAPI** | All microservices | `APIRouter`, `BackgroundTasks`, `UploadFile`, `Depends` |
| **SQLModel** | ORM + SQLite | `SQLModel`, `Field`, `Session`, `select` |
| **DeepFace** | Face verification | `DeepFace.verify()`, `DeepFace.find()` |
| **RetinaFace** | Face detection | `RetinaFace.detect_faces()` |
| **Jinja2** | HTML templating | `Jinja2Templates.TemplateResponse()` |
| **uvicorn** | ASGI server | `uvicorn.run(host, port, reload)` |

---

## 2. New Dependencies — Grading Engine

### 2.1 PDF Handling

```python
# requirements additions
pdfplumber==0.11.4        # Direct text extraction from digital PDFs
pdf2image==1.17.0          # PDF → PIL Image (requires poppler-utils system pkg)
Pillow==10.4.0             # Image processing
pytesseract==0.3.13        # Tesseract OCR wrapper (requires tesseract binary)
```

**Usage patterns:**

```python
import pdfplumber

# Digital PDF text extraction
with pdfplumber.open("sheet.pdf") as pdf:
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    confidence = len(text.strip()) / max(1, pdf.pages[0].width * pdf.pages[0].height / 100)

# PDF to images for handwriting
from pdf2image import convert_from_path
images = convert_from_path("sheet.pdf", dpi=200)
# images: List[PIL.Image]

# Tesseract OCR
import pytesseract
text = pytesseract.image_to_string(images[0], lang="eng", config="--psm 6")
```

### 2.2 NV API (NVIDIA NIM) Integration

```python
# requirements additions
httpx==0.27.0             # Async HTTP client for NV API calls
tenacity==8.3.0           # Retry logic with exponential backoff
```

**Pattern: Async NV API client with retry**

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class NVAPIClient:
    def __init__(self, api_key: str, base_url: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.base_url = base_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
        json_mode: bool = False
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
```

**Pattern: Semaphore-limited concurrent grading**

```python
import asyncio

semaphore = asyncio.Semaphore(5)  # max 5 concurrent NV API calls

async def grade_with_limit(client, question, ref, student_ans, max_marks):
    async with semaphore:
        return await client.chat_completion(...)
```

### 2.3 Background Job Processing

```python
# FastAPI BackgroundTasks pattern for long-running grading jobs
from fastapi import BackgroundTasks

@app.post("/exam/{exam_id}/submit-sheets")
async def submit_sheets(
    exam_id: int,
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    job = GradingJob(exam_id=exam_id, status="queued", total_sheets=len(files))
    session.add(job)
    session.commit()
    
    # Save files to disk first, then queue processing
    saved_paths = await save_uploaded_sheets(files, exam_id)
    background_tasks.add_task(run_grading_pipeline, job.id, saved_paths, exam_id)
    
    return {"job_id": job.id, "status": "queued"}

async def run_grading_pipeline(job_id: int, sheet_paths: list[str], exam_id: int):
    # Update job status, process each sheet, update progress in DB
    ...
```

### 2.4 PDF Report Generation

```python
# requirements additions
reportlab==4.2.0          # PDF generation for grade reports
```

```python
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

def generate_student_report_pdf(student_data: dict, output_path: str):
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    # Header
    elements.append(Paragraph(f"Grade Report - {student_data['name']}", styles['Title']))
    
    # Question breakdown table
    table_data = [["Q#", "Question", "Max", "Awarded", "Feedback"]]
    for q in student_data['questions']:
        table_data.append([q['q_number'], q['text'][:50], q['max_marks'], 
                           q['awarded_marks'], q['feedback'][:60]])
    
    table = Table(table_data, colWidths=[30, 200, 40, 50, 180])
    elements.append(table)
    doc.build(elements)
```

---

## 3. New Dependencies — Student Portal

```python
# requirements additions
python-jose[cryptography]==3.3.0   # JWT tokens for student auth
passlib[bcrypt]==1.7.4             # Password hashing
python-multipart==0.0.9            # File uploads (already in v1 likely)
```

**JWT Auth pattern:**

```python
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=24)):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

async def get_current_student(token: str = Depends(oauth2_scheme)):
    try:
        payload = verify_token(token)
        return payload["sub"]  # roll_no
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

---

## 4. OCR Routing Logic

```python
HANDWRITING_CHAR_THRESHOLD = 50

async def route_ocr(pdf_path: str) -> str:
    """Route PDF to appropriate OCR method."""
    # Try digital extraction first
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    
    if len(text.strip()) >= HANDWRITING_CHAR_THRESHOLD:
        return text  # Digital PDF — use directly
    
    # Fall back to image OCR
    images = convert_from_path(pdf_path, dpi=200)
    
    # Try Tesseract first (faster, cheaper)
    tesseract_text = "\n".join(
        pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        for img in images
    )
    
    if len(tesseract_text.strip()) >= HANDWRITING_CHAR_THRESHOLD:
        return tesseract_text  # Typed scan — Tesseract works
    
    # Last resort: NV Vision LLM for handwriting
    return await ocr_with_vision_llm(images)
```

---

## 5. Grading Algorithm

```python
def compute_final_marks(questions: list[dict]) -> float:
    """
    Final mark = sum(correlation_score_i × max_marks_i) for all questions i
    
    With professor override support:
    If override exists for question i, use override instead of AI score.
    """
    total = 0.0
    for q in questions:
        if q.get("professor_override") is not None:
            total += q["professor_override"]
        else:
            total += q["correlation_score"] * q["max_marks"]
    return round(total, 2)

def compute_class_statistics(results: list[dict]) -> dict:
    scores = [r["total"] for r in results]
    return {
        "mean": statistics.mean(scores),
        "median": statistics.median(scores),
        "std_dev": statistics.stdev(scores) if len(scores) > 1 else 0,
        "highest": max(scores),
        "lowest": min(scores),
        "pass_count": sum(1 for s in scores if s >= 0.4 * max_total)
    }
```

---

## 6. Answer Segmentation (Question Splitting)

When raw OCR text contains all answers mixed together, split by question:

```python
async def segment_answers_by_question(
    raw_text: str, 
    question_count: int,
    client: NVAPIClient
) -> dict[int, str]:
    """
    Use Kimi K2.5 to intelligently split answer text by question number.
    Returns {q_number: answer_text}
    """
    prompt = f"""
The following is a student's complete answer sheet OCR text.
Split it into {question_count} separate answers by question number.

Rules:
- Look for markers like "Q1", "Question 1", "1.", "Ans 1", "(1)" etc.
- If markers are unclear, split by logical paragraph breaks.
- Return ONLY valid JSON: {{"1": "answer text...", "2": "answer text...", ...}}

Answer sheet text:
{raw_text}
"""
    response = await client.chat_completion(
        model=KIMI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        json_mode=True
    )
    return json.loads(response)
```

---

## 7. Frontend Skills

### 7.1 Attendance Calendar Heatmap (Vanilla JS)

```javascript
// Render session heatmap grid in Student Portal
function renderAttendanceHeatmap(sessions, containerId) {
    const container = document.getElementById(containerId);
    sessions.forEach(session => {
        const cell = document.createElement('div');
        cell.className = `heatmap-cell ${session.status}`;  // present | absent | late
        cell.title = `${session.date} — ${session.method}`;
        container.appendChild(cell);
    });
}
```

### 7.2 Progress Polling (Grading Job Status)

```javascript
async function pollGradingJob(jobId, examId) {
    const poll = async () => {
        const res = await fetch(`/exam/${examId}/job/${jobId}/status`);
        const data = await res.json();
        updateProgressBar(data.progress_pct);
        if (data.status === 'completed') {
            showResultsPanel(examId);
        } else if (data.status !== 'failed') {
            setTimeout(poll, 2000);  // Poll every 2 seconds
        }
    };
    await poll();
}
```

---

## 8. Full Requirements.txt (v2)

```
# Inherited from v1
fastapi
uvicorn[standard]
sqlmodel
deepface
retina-face
qrcode[pil]
python-multipart
jinja2

# Grading Engine
pdfplumber
pdf2image
Pillow
pytesseract
httpx
tenacity
reportlab

# Student Portal Auth
python-jose[cryptography]
passlib[bcrypt]

# Utilities
python-dotenv
aiofiles
statistics
```

---

## 9. Environment Variables (.env)

```bash
# NV API
NV_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx
NV_API_BASE=https://integrate.api.nvidia.com/v1
KIMI_MODEL=moonshotai/kimi-k2-5
VISION_MODEL=meta/llama-3.2-90b-vision-instruct

# Student Auth
STUDENT_JWT_SECRET=<generate-with-openssl-rand-hex-32>

# App Config
IRIS_HOST=0.0.0.0
PROF_DASH_PORT=8000
AI_ENGINE_PORT=8001
STUDENT_APP_PORT=8002
GRADING_ENGINE_PORT=8003
STUDENT_PORTAL_PORT=8004

# OCR
TESSERACT_CMD=/usr/bin/tesseract
OCR_HANDWRITING_THRESHOLD=50

# Limits
MAX_CONCURRENT_NV_CALLS=5
GRADING_RETRY_ATTEMPTS=3
MAX_UPLOAD_SIZE_MB=50
SHEET_RETENTION_DAYS=90
```
