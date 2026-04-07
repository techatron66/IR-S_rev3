# IRIS v2 — Task Tracker
## Ordered Implementation Checklist

Legend: `[ ]` = pending · `[~]` = in progress · `[x]` = done · `[!]` = blocked

---

## Phase 0 — Foundation

- [ ] **P0-1** Restructure repo into `services/`, `core/`, new template subdirs
- [ ] **P0-2** Add new requirements to `requirements.txt` (`pdfplumber`, `pdf2image`, `Pillow`, `pytesseract`, `httpx`, `tenacity`, `reportlab`, `python-jose`, `passlib`, `python-dotenv`, `aiofiles`)
- [ ] **P0-3** Install system packages: `tesseract-ocr`, `poppler-utils`
- [ ] **P0-4** Create `.env` with all variables (see `skill.md §9`)
- [ ] **P0-5** Create `core/config.py` — pydantic `BaseSettings` loading from `.env`
- [ ] **P0-6** Create `core/database.py` — shared SQLite engine with WAL mode, session factory
- [ ] **P0-7** Extend `core/models.py` — add `Exam`, `ExamQuestion`, `StudentAnswer`, `GradingJob`, `StudentUser`, `Dispute`, `Notification` tables
- [ ] **P0-8** Run `SQLModel.metadata.create_all(engine)` — verify new tables in DB
- [ ] **P0-9** Create `core/nv_client.py` — `NVAPIClient` with `chat_completion()`, `vision_ocr()`, semaphore, tenacity retry
- [ ] **P0-10** Verify NV API key works: ping Kimi K2.5 with a test prompt
- [ ] **P0-11** Create `start_all.sh` launcher script

---

## Phase 1 — Grading Engine (`4_grading_engine.py`)

### 1A: Exam Management
- [ ] **P1-1** FastAPI app scaffold with 3 routers: `exam_router`, `grading_router`, `report_router`
- [ ] **P1-2** `POST /exam/create` — create exam + questions in DB
- [ ] **P1-3** `POST /exam/{id}/upload-question-paper` — save PDF, run OCR, return extracted questions
- [ ] **P1-4** `POST /exam/{id}/confirm-questions` — upsert confirmed questions with reference answers

### 1B: OCR Pipeline
- [ ] **P1-5** Implement `route_ocr(pdf_path)` — pdfplumber → Tesseract → NV Vision LLM cascade
- [ ] **P1-6** Implement `ocr_with_tesseract(images)` — pytesseract with `--psm 6`
- [ ] **P1-7** Implement `ocr_with_vision_llm(images, client)` — NV Vision LLM transcription
- [ ] **P1-8** Test OCR cascade with 3 PDF types: digital, scanned typed, handwritten sample

### 1C: Grading Pipeline
- [ ] **P1-9** Implement `segment_answers_by_question(raw_text, q_count, client)` — Kimi K2.5 splitter
- [ ] **P1-10** Implement `grade_answer(question, ref_answer, student_answer, max_marks, client)` — Kimi K2.5 with JSON mode
- [ ] **P1-11** Define `GRADING_SYSTEM_PROMPT` constant (see `design.md §6.1`)
- [ ] **P1-12** Implement `compute_final_marks(questions)` — with professor override support
- [ ] **P1-13** Implement `compute_class_statistics(results)` — mean, median, std, pass rate

### 1D: Sheet Submission & Job Tracking
- [ ] **P1-14** `POST /exam/{id}/submit-sheets` — save files, create GradingJob, dispatch BackgroundTask
- [ ] **P1-15** Implement `run_grading_pipeline(job_id, exam_id)` background task — full pipeline per sheet
- [ ] **P1-16** Update `GradingJob.processed_sheets` and `status` after each sheet
- [ ] **P1-17** Handle per-sheet failures gracefully (log error, continue other sheets)
- [ ] **P1-18** `GET /exam/{id}/job/{job_id}/status` — poll endpoint returning `{status, progress_pct}`

### 1E: Results & Export
- [ ] **P1-19** `GET /exam/{id}/results` — full results with per-question breakdown
- [ ] **P1-20** `GET /exam/{id}/export/csv` — CSV with all student scores
- [ ] **P1-21** `GET /exam/{id}/export/json` — JSON dump
- [ ] **P1-22** `GET /exam/{id}/export/pdf` — reportlab class grade report
- [ ] **P1-23** `GET /exam/{id}/student/{roll_no}/report/pdf` — per-student grade report PDF
- [ ] **P1-24** `POST /exam/{id}/student/{roll_no}/override` — professor mark override with reason

### 1F: End-to-End Test
- [ ] **P1-25** Integration test: create exam → upload Q paper → confirm → submit 3 sheets → poll → verify results

---

## Phase 2 — Student Portal (`5_student_portal.py`)

### 2A: Auth
- [ ] **P2-1** FastAPI app scaffold with JWT middleware
- [ ] **P2-2** `POST /admin/students/import` — bulk CSV import, create `StudentUser` records
- [ ] **P2-3** `POST /student/login` — bcrypt verify + JWT issue
- [ ] **P2-4** `GET /student/me` — current student profile from JWT

### 2B: Attendance View
- [ ] **P2-5** `GET /student/me/classes` — class list with attendance % per class
- [ ] **P2-6** `GET /student/me/class/{id}/attendance` — session-level breakdown
- [ ] **P2-7** Compute attendance % correctly including all session types (QR, face, manual)
- [ ] **P2-8** Alert flag when attendance < 75%

### 2C: Marks View
- [ ] **P2-9** `GET /student/me/exams` — exams list with score, rank, class average
- [ ] **P2-10** `GET /student/me/exam/{id}/breakdown` — per-question marks + AI feedback
- [ ] **P2-11** Compute rank within class for each exam
- [ ] **P2-12** `GET /student/me/exam/{id}/report/pdf` — download own grade report

### 2D: Dispute System
- [ ] **P2-13** `POST /student/dispute/attendance` — create attendance dispute
- [ ] **P2-14** `POST /student/dispute/marks` — create marks dispute with question reference
- [ ] **P2-15** `GET /student/disputes` — list own disputes with status
- [ ] **P2-16** Evidence file upload support for disputes (optional, max 10MB)

### 2E: Professor Dispute Management (add to prof dashboard)
- [ ] **P2-17** `GET /professor/disputes` — all pending disputes paginated
- [ ] **P2-18** `POST /professor/dispute/{id}/resolve` — accept/reject/request-info with response text
- [ ] **P2-19** Auto-update attendance/marks when dispute accepted
- [ ] **P2-20** Immutable audit log for all dispute state changes

### 2F: Notifications
- [ ] **P2-21** `Notification` table and CRUD
- [ ] **P2-22** `GET /student/notifications` — unread notifications list
- [ ] **P2-23** Trigger notifications on: results published, dispute resolved, attendance updated

### 2G: HTML Templates
- [ ] **P2-24** `student_portal/login.html` — clean login form
- [ ] **P2-25** `student_portal/dashboard.html` — tab layout shell
- [ ] **P2-26** `student_portal/attendance.html` — class cards + session heatmap
- [ ] **P2-27** `student_portal/marks.html` — exam cards + expandable question breakdown
- [ ] **P2-28** `student_portal/disputes.html` — dispute form + status list
- [ ] **P2-29** Add JS polling for notifications (30s interval)

---

## Phase 3 — Professor Dashboard Extension

### 3A: New Tabs
- [ ] **P3-1** Add "Exams & Grading" tab to `prof_dash.html` main layout
- [ ] **P3-2** Add "Disputes" tab with pending count badge
- [ ] **P3-3** Add "Students" tab for bulk import

### 3B: Grading UI Routes (in `1_prof_dash.py`)
- [ ] **P3-4** `GET /dashboard/exams` — exams list with status badges (draft/grading/published)
- [ ] **P3-5** `GET /dashboard/exam/new` — exam creation form (name, date, question table)
- [ ] **P3-6** `POST /dashboard/exam/new` — form submit → call grading engine API
- [ ] **P3-7** `GET /dashboard/exam/{id}` — exam detail: question paper, grading status, results
- [ ] **P3-8** Question paper upload zone with OCR preview panel
- [ ] **P3-9** Answer sheets bulk upload zone with per-file status list
- [ ] **P3-10** Grading progress bar (poll `/exam/{id}/job/{job_id}/status` every 2s)
- [ ] **P3-11** Results table: sortable by name/score, search, per-row expand for breakdown
- [ ] **P3-12** Mark override modal: select question, enter new marks, reason field
- [ ] **P3-13** Export buttons: CSV / PDF / JSON

### 3C: Disputes UI
- [ ] **P3-14** Disputes tab: filter by type (attendance/marks), status (pending/resolved)
- [ ] **P3-15** Dispute detail modal: student info, dispute reason, evidence link
- [ ] **P3-16** Accept / Reject / Request Info buttons with response textarea

### 3D: Student Import UI
- [ ] **P3-17** CSV upload form for bulk student import
- [ ] **P3-18** Preview table showing parsed students before import
- [ ] **P3-19** Import result summary (success/failed/skipped rows)

---

## Phase 4 — Polish & Hardening

- [ ] **P4-1** `start_all.sh` — tested on clean machine
- [ ] **P4-2** WAL mode enabled on SQLite at startup in all services
- [ ] **P4-3** NV API quota exceeded handling: pause job, set status "paused", notify professor
- [ ] **P4-4** Empty OCR result handling: flag sheet `requires_manual_review`, skip grading
- [ ] **P4-5** File validation: MIME type + magic bytes check on all uploads
- [ ] **P4-6** File size enforcement: reject uploads > 50MB
- [ ] **P4-7** Sheet retention: scheduled cleanup of raw sheets older than `SHEET_RETENTION_DAYS`
- [ ] **P4-8** `X-Internal-Key` header verification for inter-service calls
- [ ] **P4-9** Rate limit NV API: verify semaphore works under load (test with 10 concurrent)
- [ ] **P4-10** Update `README.md` — v2 architecture, new setup steps, feature list
- [ ] **P4-11** Full end-to-end test: all 5 services running simultaneously, complete user journey

---

## Backlog (Post-MVP)

- [ ] **BACK-1** WebSocket-based real-time grading progress (replace polling)
- [ ] **BACK-2** Student answer sheet comparison view (side-by-side: scanned vs AI analysis)
- [ ] **BACK-3** Multi-language OCR support (Telugu, Hindi) via Tesseract lang packs
- [ ] **BACK-4** Grade curve / moderation tool for professor
- [ ] **BACK-5** Email notifications for students (SMTP integration)
- [ ] **BACK-6** Analytics dashboard: class performance trends over time
- [ ] **BACK-7** Mobile-responsive student portal (currently desktop-first)
- [ ] **BACK-8** Docker Compose setup for one-command deployment
- [ ] **BACK-9** Plagiarism detection between student answers (cosine similarity check before grading)
- [ ] **BACK-10** Rubric builder: professors define custom scoring criteria per question
