# IRIS v2 — Execution Plan
## Phased Implementation Guide

---

## Ground Rules

- **Never break v1**: All new services are additive. Existing ports 8000–8002 stay untouched until Phase 4.
- **One phase at a time**: Each phase is independently testable and deployable.
- **DB migrations are additive**: Only `ALTER TABLE ADD COLUMN` or new tables — never destructive.
- **Feature flags**: New tabs/routes in the professor dashboard use `if GRADING_ENABLED` flags until stable.

---

## Phase 0 — Environment & Foundation (Day 1)

### 0.1 Repo Restructure

```
iris_v2/
├── services/
│   ├── 1_prof_dash.py          # unchanged
│   ├── 2_gpu_server.py         # unchanged
│   ├── 3_student_app.py        # unchanged
│   ├── 4_grading_engine.py     # NEW
│   └── 5_student_portal.py     # NEW
├── core/
│   ├── config.py               # NEW — centralized env config
│   ├── database.py             # NEW — shared DB engine/session factory
│   ├── models.py               # EXTENDED — new tables added
│   └── nv_client.py            # NEW — NV API async client
├── templates/
│   ├── prof/                   # existing templates moved here
│   ├── student_app/            # existing moved here
│   ├── grading/                # NEW
│   └── student_portal/         # NEW
├── static/
├── exam_db/                    # NEW directory
├── disputes/                   # NEW directory
├── .env
├── requirements.txt            # extended
└── start_all.sh                # NEW — convenience launcher
```

### 0.2 Install New Dependencies

```bash
pip install pdfplumber pdf2image Pillow pytesseract httpx tenacity \
            reportlab python-jose[cryptography] passlib[bcrypt] \
            python-dotenv aiofiles

# System packages
sudo apt-get install -y tesseract-ocr poppler-utils
```

### 0.3 Create `core/config.py`

Load all `.env` values with `python-dotenv`. Expose as typed `Settings` object using pydantic `BaseSettings`.

### 0.4 Create `core/nv_client.py`

Implement `NVAPIClient` with:
- `chat_completion()` async method
- `vision_ocr()` async method (multimodal)
- Semaphore limit: `asyncio.Semaphore(settings.MAX_CONCURRENT_NV_CALLS)`
- Tenacity retry decorator (3 attempts, exponential backoff)
- Unit test: `test_nv_client.py` with mock HTTP responses

### 0.5 Extend `core/models.py`

Add new SQLModel tables to existing `models.py`:
- `Exam`, `ExamQuestion`, `StudentAnswer`
- `GradingJob`
- `StudentUser`, `Dispute`

Run schema migration:
```python
SQLModel.metadata.create_all(engine)  # safe — only creates new tables
```

**Deliverable:** All 5 services start on their ports with no import errors. New DB tables exist.

---

## Phase 1 — Grading Engine Core (Days 2–5)

### 1.1 Create `services/4_grading_engine.py`

**Step 1:** FastAPI app scaffold with router structure:
```
/exam          → exam_router
/grade         → grading_router
/report        → report_router
```

**Step 2:** Implement `POST /exam/create`
- Accept `class_id`, `exam_name`, `date`, `questions[]`
- Insert `Exam` + `ExamQuestion` rows
- Return `{exam_id}`

**Step 3:** Implement `POST /exam/{id}/upload-question-paper`
- Accept PDF/image upload (`UploadFile`)
- Save to `exam_db/{exam_id}/question_paper.pdf`
- Run OCR pipeline:
  - `pdfplumber` text extract
  - If insufficient → Tesseract
  - If still insufficient → NV Vision LLM
- Parse extracted text → attempt auto-detect questions by number pattern
- Return `{extracted_questions, requires_confirmation: bool}`

**Step 4:** Implement `POST /exam/{id}/confirm-questions`
- Accept professor-edited question list
- Upsert `ExamQuestion` rows with `reference_answer` if provided

**Step 5:** Implement `POST /exam/{id}/submit-sheets`
- Accept `list[UploadFile]`
- Validate filenames match roll number pattern
- Save to `exam_db/{exam_id}/sheets/raw/`
- Create `GradingJob` record (status: queued)
- Dispatch `BackgroundTask`: `run_grading_pipeline(job_id, exam_id)`
- Return `{job_id, status: "queued"}`

**Step 6:** Implement `run_grading_pipeline()` background task:
```
For each sheet:
  1. route_ocr(pdf_path) → raw_text
  2. segment_answers_by_question(raw_text, question_count) → {q_num: answer}
  3. For each question concurrently (semaphore limited):
       grade_answer(question, ref_answer, student_answer, max_marks)
       → {correlation_score, awarded_marks, rationale, feedback, missing_concepts}
  4. compute_final_marks(questions)
  5. Insert StudentAnswer rows
  6. Update GradingJob.processed_sheets += 1
  7. Save OCR text to exam_db/{id}/sheets/ocr/{roll_no}.json
```

**Step 7:** Implement `GET /exam/{id}/job/{job_id}/status`
- Query `GradingJob` → return `{status, progress_pct, completed, failed}`

**Step 8:** Implement `GET /exam/{id}/results`
- Join `StudentAnswer + ExamQuestion + StudentUser`
- Return sorted results with full breakdown

**Step 9:** Implement `GET /exam/{id}/export/{format}`
- `csv`: `csv.writer` from results dict
- `pdf`: `reportlab` grade report
- `json`: direct JSON dump

**Step 10:** Implement `POST /exam/{id}/student/{roll_no}/override`
- Update `StudentAnswer.professor_override` + `override_reason`
- Recompute total for student

**Test checkpoint:** Upload a sample PDF answer sheet, trigger grading, poll status, verify results JSON.

---

## Phase 2 — Student Portal (Days 6–9)

### 2.1 Create `services/5_student_portal.py`

**Step 1:** FastAPI app with JWT auth middleware

**Step 2:** Implement student registration endpoint (professor-invoked or bulk CSV import):
```
POST /admin/students/import
Body: CSV (roll_no, name, email, class_ids[])
Creates StudentUser records with temp passwords
```

**Step 3:** Implement `POST /student/login`
- Verify `roll_no + password` against `bcrypt` hash
- Issue JWT (24h expiry)
- Return `{token, name, roll_no}`

**Step 4:** Implement `GET /student/me/classes`
- Parse `StudentUser.class_ids` (JSON array)
- Join attendance data from main DB (cross-DB query or shared DB)
- Compute `attendance_pct` per class
- Return class list with stats

**Step 5:** Implement `GET /student/me/class/{id}/attendance`
- Fetch all `AttendanceRecord` rows for student+class
- Group by date → `{date, status, method}`
- Return with summary stats

**Step 6:** Implement exam endpoints:
- `GET /student/me/exams` — list all exams for enrolled classes
- `GET /student/me/exam/{id}/breakdown` — per-question detail with AI feedback

**Step 7:** Implement dispute endpoints:
- `POST /student/dispute/attendance` → create `Dispute(type="attendance")`
- `POST /student/dispute/marks` → create `Dispute(type="marks")`
- `GET /student/disputes` → list disputes with status

**Step 8:** Implement professor-side dispute endpoints (add to prof dashboard service):
- `GET /professor/disputes` → pending disputes list
- `POST /professor/dispute/{id}/resolve` → accept/reject with response

**Step 9:** Build HTML templates for student portal:
- `student_portal/login.html`
- `student_portal/dashboard.html` (tab layout)
- `student_portal/attendance.html` (heatmap calendar)
- `student_portal/marks.html` (exam cards + breakdown)
- `student_portal/disputes.html` (form + list)

**Test checkpoint:** Student login → view attendance → view marks → submit dispute → professor resolves → student sees resolution.

---

## Phase 3 — Professor Dashboard Extensions (Days 10–12)

### 3.1 Extend `1_prof_dash.py`

**Step 1:** Add new tab to main dashboard template: "Exams & Grading", "Disputes"

**Step 2:** Add routes proxying to Grading Engine (or direct DB access):
- `GET /dashboard/exams` → list exams with status badges
- `GET /dashboard/exam/{id}` → exam detail + results table
- HTML forms for exam creation, question paper upload, sheet upload

**Step 3:** Add dispute management routes:
- `GET /dashboard/disputes` → list pending disputes
- `POST /dashboard/dispute/{id}/resolve`

**Step 4:** Add student management → bulk import CSV route (calls student portal service)

**Step 5:** Wire frontend JavaScript:
- Drag-drop file upload zones (question paper, answer sheets)
- Progress bar polling loop for grading jobs
- Results table with sort, search, export buttons
- Dispute modal with accept/reject/respond controls

**Test checkpoint:** Full end-to-end: create exam → upload Q paper → confirm questions → upload 5 sample sheets → watch grading progress → view results → override one mark → export CSV.

---

## Phase 4 — Polish & Integration (Days 13–15)

### 4.1 Unified Launcher

```bash
# start_all.sh
#!/bin/bash
echo "Starting IRIS v2..."
python services/2_gpu_server.py &     # AI Face Engine :8001
python services/3_student_app.py &    # Student QR App :8002
python services/4_grading_engine.py & # Grading Engine :8003
python services/5_student_portal.py & # Student Portal :8004
python services/1_prof_dash.py        # Prof Dashboard :8000 (foreground)
```

### 4.2 Cross-Service DB Access

Since all services use the same `main_app.db` (SQLite), ensure:
- WAL mode enabled: `PRAGMA journal_mode=WAL;` at startup
- All services use same `core/database.py` session factory
- Write operations serialized per table (SQLite handles read concurrency)

### 4.3 Error Handling Hardening

- Grading failure for individual sheet → mark `StudentAnswer.status = "failed"`, continue pipeline
- NV API quota exceeded → pause job, update `GradingJob.status = "paused"`, alert professor
- OCR produces empty text → flag sheet as `requires_manual_review`

### 4.4 Notifications

Add lightweight notification table:
```python
class Notification(SQLModel, table=True):
    id: int = Field(primary_key=True)
    user_type: str  # professor | student
    user_id: int
    message: str
    link: Optional[str]
    read: bool = False
    created_at: datetime
```

Student portal polls `GET /student/notifications` every 30s (long-poll or simple interval).

### 4.5 README Update

Update `README.md` with v2 architecture diagram, new setup steps, and feature overview.

---

## Testing Strategy

| Layer | Method |
|---|---|
| NV API client | Mock HTTP responses with `respx` |
| OCR routing | Sample PDFs: digital, scanned, handwritten |
| Grading algorithm | Known Q&A pairs with expected score ranges |
| Grading pipeline | End-to-end with 3–5 real sample sheets |
| Student auth | JWT expiry, invalid token, wrong password |
| Dispute flow | Create → resolve → verify DB state |
| Export | CSV/PDF/JSON output validity |

---

## Deployment Checklist

- [ ] `.env` file populated with real NV_API_KEY
- [ ] `tesseract` and `poppler-utils` installed system-wide
- [ ] `exam_db/` and `disputes/` directories created with write permissions
- [ ] DB schema migration run (`SQLModel.metadata.create_all`)
- [ ] NV API connectivity test: `python -c "from core.nv_client import NVAPIClient; ..."`
- [ ] All 5 services start without errors
- [ ] Sample grading job completes end-to-end
- [ ] Student login + marks view works
- [ ] Dispute cycle works end-to-end
