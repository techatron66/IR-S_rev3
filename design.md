# IRIS v2 — AIO Lecturer Intelligence Platform
## System Design Document

---

## 1. Vision

IRIS v2 evolves from a smart attendance tracker into a complete **All-In-One Lecturer Intelligence Platform**. It unifies attendance management, AI-powered answer sheet grading, and a student self-service portal under a single cohesive system. The core philosophy is **zero-friction for lecturers, full transparency for students**.

---

## 2. Current System Baseline (IRIS v1)

| Service | Port | Role |
|---|---|---|
| Professor Dashboard (`1_prof_dash.py`) | 8000 | Auth, DB, UI, class management |
| AI Engine (`2_gpu_server.py`) | 8001 | DeepFace/FaceNet512 face verification |
| Student App (`3_student_app.py`) | 8002 | QR scan → selfie → check-in |

**Stack:** FastAPI + SQLModel (SQLite) + DeepFace + RetinaFace + Jinja2 HTML templates

---

## 3. IRIS v2 — Extended Architecture

### 3.1 Microservice Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        IRIS v2 Platform                         │
│                                                                 │
│  ┌──────────────────┐    ┌─────────────────┐                   │
│  │  Prof Dashboard  │    │   AI Face Engine │                   │
│  │  :8000 (FastAPI) │◄───│   :8001 (FastAPI)│                   │
│  │  Auth, Classes,  │    │  DeepFace/Retina │                   │
│  │  Attendance Mgmt │    │  FaceNet512      │                   │
│  └────────┬─────────┘    └─────────────────┘                   │
│           │                                                     │
│  ┌────────▼─────────┐    ┌─────────────────┐                   │
│  │  Grading Engine  │    │  Student Portal  │                   │
│  │  :8003 (FastAPI) │    │  :8004 (FastAPI) │                   │
│  │  OCR → NV API    │    │  Dashboard, Marks│                   │
│  │  Kimi K2.5 Grade │    │  Disputes, Track │                   │
│  └────────┬─────────┘    └────────┬─────────┘                  │
│           │                       │                             │
│  ┌────────▼───────────────────────▼────────────────────────┐   │
│  │                    Student App :8002                     │   │
│  │               QR Scan → Selfie → Check-in               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                SQLite (main_app.db)                     │   │
│  │     + File System (student_db/, exams/, reports/)       │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 New Services

| Service | Port | Responsibility |
|---|---|---|
| Grading Engine (`4_grading_engine.py`) | 8003 | OCR pipeline, NV API grading, report generation |
| Student Portal (`5_student_portal.py`) | 8004 | Student login, attendance view, marks, disputes |

---

## 4. Module Designs

### 4.1 Module: Answer Sheet Grading Engine

#### 4.1.1 Workflow

```
Lecturer Input
     │
     ├─► Question Paper Upload (PDF/Image)
     │         │
     │         ▼
     │   [OCR / Vision LLM]
     │   Extract questions + structure
     │         │
     │         ▼
     │   Question Schema:
     │   [{q_id, question_text, max_marks, reference_answer?}]
     │
     ├─► Marks per Question (form input or JSON)
     │
     └─► Student Answer Sheets (bulk PDF/image, named by roll no)
               │
               ▼
         [OCR Pipeline per sheet]
         ┌────────────────────────────────────┐
         │  1. RetinaFace-free path           │
         │  2. PDF → image (pdf2image)        │
         │  3. Image → text (Tesseract/       │
         │     NV Vision LLM for handwriting) │
         └────────────────────┬───────────────┘
                              │
                              ▼
                    Per-question answer extraction
                    (split by Q1/Q2 markers or LLM)
                              │
                              ▼
               ┌──────────────────────────────┐
               │     NV API: Kimi K2.5         │
               │  Semantic Grading Prompt      │
               │                              │
               │  System: "You are an expert  │
               │  examiner. Score the student │
               │  answer vs reference on a    │
               │  0–1 correlation scale."     │
               │                              │
               │  Input: question, ref_answer,│
               │  student_answer, rubric      │
               │                              │
               │  Output: {score, rationale,  │
               │  feedback, partial_credit[]} │
               └──────────────┬───────────────┘
                              │
                              ▼
               Final Mark = correlation_score × max_marks
               (per question, summed for total)
                              │
                              ▼
               Grade Report (per student, per class)
               JSON + PDF + CSV export
```

#### 4.1.2 Grading Prompt Architecture (Kimi K2.5 via NV API)

```python
GRADING_SYSTEM_PROMPT = """
You are an expert academic examiner with deep subject matter expertise.
Your task is to evaluate a student's answer to a specific question.

Rules:
- Score the semantic correlation between the student's answer and the
  reference answer on a scale of 0.0 to 1.0
- 1.0 = complete, accurate, and well-articulated answer
- 0.5 = partially correct, missing key concepts
- 0.0 = incorrect or completely off-topic
- Consider conceptual understanding, not just keyword matching
- Account for alternative valid explanations
- Provide actionable feedback for improvement

Output ONLY valid JSON:
{
  "correlation_score": <float 0.0-1.0>,
  "awarded_marks": <float>,
  "rationale": "<one sentence explanation>",
  "feedback": "<constructive 1-2 sentence feedback for student>",
  "missing_concepts": ["<concept1>", "<concept2>"]
}
"""
```

#### 4.1.3 OCR Strategy

| Answer Sheet Type | OCR Method |
|---|---|
| Printed / typed PDF | `pdfplumber` direct text extraction |
| Scanned typed paper | `Tesseract OCR` (pytesseract) |
| Handwritten sheets | `NV Vision LLM` (LLaMA 3.2 Vision or similar NIM) |
| Mixed | Detection heuristic → route accordingly |

Handwriting detection heuristic: if pdfplumber text confidence < threshold or char count < 50% of expected, route to Vision LLM.

#### 4.1.4 API Endpoints (Grading Engine :8003)

```
POST /exam/create
  Body: {class_id, exam_name, date, questions: [{q_id, text, max_marks}]}
  Returns: {exam_id}

POST /exam/{exam_id}/upload-question-paper
  Body: multipart file (PDF/image)
  Returns: {extracted_questions: [...], requires_confirmation: bool}

POST /exam/{exam_id}/confirm-questions
  Body: {questions: [{q_id, text, max_marks, reference_answer}]}
  Returns: {confirmed: true}

POST /exam/{exam_id}/submit-sheets
  Body: multipart files[] (named: {roll_no}.pdf or bulk zip)
  Returns: {job_id, status: "queued"}

GET /exam/{exam_id}/job/{job_id}/status
  Returns: {status, progress_pct, completed, failed}

GET /exam/{exam_id}/results
  Returns: {students: [{roll_no, name, total, breakdown: [{q_id, score, awarded, feedback}]}]}

GET /exam/{exam_id}/export/{format}
  format: csv | pdf | json
  Returns: file download

POST /exam/{exam_id}/student/{roll_no}/override
  Body: {q_id, new_marks, reason}  (professor manual override)
  Returns: {updated: true}
```

---

### 4.2 Module: Student Portal

#### 4.2.1 Features

```
Student Login (roll_no + password or OTP)
          │
          ├─── Attendance View
          │     ├── Per class attendance %
          │     ├── Session-wise breakdown (date, status, method)
          │     ├── Projected shortfall alert (<75%)
          │     └── Calendar heatmap view
          │
          ├─── Marks Dashboard
          │     ├── Per exam: total score, rank, class average
          │     ├── Per question breakdown with AI feedback
          │     ├── Progress chart across exams
          │     └── Download grade report PDF
          │
          ├─── Dispute Center
          │     ├── Raise attendance dispute (wrong date, tech failure)
          │     ├── Raise marks dispute (specific question, reason)
          │     ├── Upload supporting evidence (photo, screenshot)
          │     ├── Track dispute status (pending/reviewed/resolved)
          │     └── Professor response thread
          │
          └─── Notifications
                ├── Upcoming exam schedule
                ├── Results published alerts
                └── Dispute resolution updates
```

#### 4.2.2 API Endpoints (Student Portal :8004)

```
POST /student/login
  Body: {roll_no, password}
  Returns: {token, student_id, name}

GET /student/me/classes
  Returns: [{class_id, name, attendance_pct, sessions_total, sessions_attended}]

GET /student/me/class/{class_id}/attendance
  Returns: {sessions: [{date, status, method, time}], summary: {...}}

GET /student/me/exams
  Returns: [{exam_id, name, class, date, total_marks, scored, rank}]

GET /student/me/exam/{exam_id}/breakdown
  Returns: {questions: [{q_id, text, max_marks, awarded, feedback, missing_concepts}]}

POST /student/dispute/attendance
  Body: {class_id, session_date, reason, evidence_url?}
  Returns: {dispute_id}

POST /student/dispute/marks
  Body: {exam_id, q_id, reason, student_explanation}
  Returns: {dispute_id}

GET /student/disputes
  Returns: [{dispute_id, type, status, created_at, professor_response}]
```

#### 4.2.3 Dispute Workflow

```
Student raises dispute
        │
        ▼
Dispute record created (status: PENDING)
        │
        ▼
Professor notified (dashboard badge)
        │
        ▼
Professor reviews → can:
  ├── Accept → auto-update attendance/marks
  ├── Reject → add reason note
  └── Request more info → student notified
        │
        ▼
Student receives resolution notification
Audit log maintained for all changes
```

---

## 5. Data Model (Extended)

### 5.1 New Tables (SQLModel)

```python
class Exam(SQLModel, table=True):
    id: int = Field(primary_key=True)
    class_id: int = Field(foreign_key="class.id")
    professor_id: int = Field(foreign_key="professor.id")
    name: str
    date: datetime
    total_marks: float
    status: str  # draft | published | graded
    created_at: datetime

class ExamQuestion(SQLModel, table=True):
    id: int = Field(primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    q_number: int
    question_text: str
    max_marks: float
    reference_answer: Optional[str]

class StudentAnswer(SQLModel, table=True):
    id: int = Field(primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    student_id: int = Field(foreign_key="student.id")
    question_id: int = Field(foreign_key="examquestion.id")
    raw_ocr_text: str
    correlation_score: float
    awarded_marks: float
    ai_rationale: str
    ai_feedback: str
    missing_concepts: str  # JSON array
    professor_override: Optional[float]
    override_reason: Optional[str]

class GradingJob(SQLModel, table=True):
    id: int = Field(primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    status: str  # queued | processing | completed | failed
    total_sheets: int
    processed_sheets: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_log: Optional[str]

class StudentUser(SQLModel, table=True):
    id: int = Field(primary_key=True)
    roll_no: str = Field(unique=True)
    name: str
    email: Optional[str]
    password_hash: str
    class_ids: str  # JSON array of enrolled class IDs

class Dispute(SQLModel, table=True):
    id: int = Field(primary_key=True)
    student_id: int = Field(foreign_key="studentuser.id")
    type: str  # attendance | marks
    ref_id: int  # session_id or student_answer_id
    reason: str
    evidence_path: Optional[str]
    status: str  # pending | reviewing | accepted | rejected
    professor_response: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
```

### 5.2 File System Structure (Extended)

```
iris_v2/
├── student_db/                  # Face photos (existing)
│   └── [Class]/stu_[RollNo]/
│
├── exam_db/                     # NEW
│   └── [exam_id]/
│       ├── question_paper.pdf
│       ├── sheets/
│       │   ├── raw/             # Uploaded originals
│       │   │   └── [roll_no].pdf
│       │   └── ocr/             # Extracted text
│       │       └── [roll_no].json
│       └── reports/
│           ├── results.json
│           ├── class_report.csv
│           └── [roll_no]_report.pdf
│
├── disputes/                    # NEW
│   └── [dispute_id]/evidence.*
│
├── prof_db/                     # Existing CSV reports
├── main_app.db                  # SQLite (extended schema)
└── templates/                   # HTML (extended)
```

---

## 6. NV API Integration Design

### 6.1 Kimi K2.5 — Semantic Grading

```python
NV_API_BASE = "https://integrate.api.nvidia.com/v1"
KIMI_MODEL = "moonshotai/kimi-k2-5"  # or current NIM slug

async def grade_answer(
    question: str,
    reference_answer: str,
    student_answer: str,
    max_marks: float
) -> GradeResult:
    payload = {
        "model": KIMI_MODEL,
        "messages": [
            {"role": "system", "content": GRADING_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
Question: {question}
Reference Answer: {reference_answer}
Student Answer: {student_answer}
Maximum Marks: {max_marks}

Evaluate and return JSON only.
            """}
        ],
        "temperature": 0.1,   # Low temp for consistency
        "max_tokens": 512,
        "response_format": {"type": "json_object"}
    }
    # POST to NV API endpoint with Bearer token
    # Parse JSON response → GradeResult
```

### 6.2 NV Vision LLM — Handwriting OCR

```python
NV_VISION_MODEL = "meta/llama-3.2-90b-vision-instruct"  # NIM

async def ocr_handwritten_sheet(image_b64: str) -> str:
    payload = {
        "model": NV_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                },
                {
                    "type": "text",
                    "text": """Transcribe all handwritten text from this exam answer sheet.
Preserve question numbers (Q1, Q2, etc.) as section headers.
Return plain text only, no formatting."""
                }
            ]
        }],
        "max_tokens": 4096
    }
```

### 6.3 Rate Limiting & Batching Strategy

- Grading jobs run as async background tasks (FastAPI BackgroundTasks)
- NV API calls: max 5 concurrent via asyncio.Semaphore
- Retry with exponential backoff (3 attempts) on rate limit (429)
- Job progress tracked in DB, polled by frontend via `/job/{id}/status`

---

## 7. Frontend Design

### 7.1 Professor Dashboard Extensions (Port 8000)

New tabs added to existing dashboard:

```
[Class Management] [Live Attendance] [📋 Exams & Grading] [📊 Analytics] [🔔 Disputes]
```

**Exams & Grading Tab:**
- Create exam form (name, date, question table with marks)
- Upload question paper (drag-drop zone with OCR preview)
- Confirm/edit extracted questions
- Bulk upload answer sheets (progress bar, per-student status)
- Results table: sortable by score, download buttons
- Per-student detail modal: question breakdown + AI feedback

**Disputes Tab:**
- List of pending disputes (attendance + marks)
- Accept / Reject / Request Info buttons
- Response text field
- Audit trail view

### 7.2 Student Portal (Port 8004)

Single-page feel with tab navigation:

```
[📅 Attendance] [📝 My Marks] [⚠️ Disputes] [🔔 Notifications]
```

**Attendance Tab:**
- Class cards with donut chart (% attended)
- Expandable session log (date, time, method: QR/Face/Manual)
- Red badge if < 75%

**My Marks Tab:**
- Exam cards: score/total, rank, class avg
- Expandable: per-question breakdown table
  - Q1: 4/5 | "Good explanation but missing..." | Feedback badge
- Download my report PDF button

**Disputes Tab:**
- New Dispute button → modal with type selector
- Active disputes list with status chips
- Thread view for professor responses

---

## 8. Security Design

| Concern | Approach |
|---|---|
| Professor auth | Existing session-based (keep) |
| Student auth | Roll number + password (bcrypt hash) |
| API inter-service | Shared secret header (X-Internal-Key) |
| File upload validation | MIME type + magic bytes check, max 50MB |
| Dispute tampering | Immutable audit log, status transitions only forward |
| NV API key | Environment variable, never in DB or logs |
| OCR data | Processed text stored, raw sheets purged after N days (configurable) |

---

## 9. Performance Considerations

| Bottleneck | Mitigation |
|---|---|
| Handwriting OCR (Vision LLM) | Async queue, batch per-page not per-sheet |
| Kimi K2.5 grading latency | Concurrent per-question calls, semaphore-limited |
| Many sheets (50+ students) | Background job with progress polling |
| SQLite concurrency | WAL mode enabled, serialize writes per exam |
| PDF rendering | pdf2image with poppler, cache rendered images |

---

## 10. Config File (config.py)

```python
NV_API_KEY: str              # from env
NV_API_BASE: str = "https://integrate.api.nvidia.com/v1"
KIMI_MODEL: str = "moonshotai/kimi-k2-5"
VISION_MODEL: str = "meta/llama-3.2-90b-vision-instruct"
OCR_HANDWRITING_THRESHOLD: int = 50   # chars below = handwritten
MAX_CONCURRENT_NV_CALLS: int = 5
GRADING_RETRY_ATTEMPTS: int = 3
SHEET_RETENTION_DAYS: int = 90
MAX_UPLOAD_SIZE_MB: int = 50
STUDENT_PORTAL_PORT: int = 8004
GRADING_ENGINE_PORT: int = 8003
```
