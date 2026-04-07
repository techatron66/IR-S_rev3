# Gemini Prompt — IRIS v2 AIO Lecturer Platform Design

---

## Prompt

You are a senior full-stack software architect specializing in Python microservices and AI-integrated educational platforms. I need you to produce a complete, production-grade technical design package for evolving an existing system.

---

### Context: The Current System (IRIS v1)

IRIS is a smart university attendance tracking system built as 3 FastAPI microservices:

1. **Professor Dashboard** (Port 8000) — FastAPI + SQLModel (SQLite) + Jinja2 HTML templates. Handles professor auth, class management, student registration, and attendance monitoring.
2. **AI Face Engine** (Port 8001) — Background FastAPI worker running DeepFace (FaceNet512 model) and RetinaFace for facial verification of student selfies.
3. **Student App** (Port 8002) — Lightweight FastAPI app. Students scan a QR code projected in class, take a selfie, and get verified instantly.

**Core flow:** Professor creates a class → registers students with 1-3 face photos → starts a session (generates QR code) → students scan QR → take selfie → AI verifies face → marks attendance automatically. Optional: professor uploads a class group photo → AI detects all faces → bulk-marks attendance.

**Tech stack:** Python 3.9+, FastAPI, SQLModel, SQLite, DeepFace, RetinaFace, Jinja2, uvicorn, qrcode[pil].

**Repo structure:**
```
iris/
├── 1_prof_dash.py
├── 2_gpu_server.py
├── 3_student_app.py
├── models.py
├── main_app.db
├── templates/
├── student_db/      # face photos
├── prof_db/         # CSV reports
└── requirements.txt
```

---

### What I Want to Build: IRIS v2

Evolve IRIS into a complete **All-In-One Lecturer Intelligence Platform** with two major additions:

---

#### Addition 1: AI-Powered Answer Sheet Grading Engine

The workflow is:
1. **Professor inputs:** Uploads the question paper (PDF or scanned image) + specifies max marks per question.
2. **Question extraction:** System OCRs the question paper and extracts individual questions. Professor confirms/edits the extracted questions and optionally provides reference answers.
3. **Student sheet submission:** Professor uploads student answer sheets in bulk (PDFs, one per student, named by roll number, or as a ZIP).
4. **OCR pipeline per sheet:** Each sheet is converted from PDF/image to text. Strategy: try `pdfplumber` for digital PDFs, fall back to `pytesseract` for typed scans, and use an NVIDIA NIM Vision LLM for handwritten sheets.
5. **Answer segmentation:** The raw OCR text is split into per-question answers (using Kimi K2.5 to identify question boundaries intelligently).
6. **AI grading:** For each question, call **Kimi K2.5 via the NVIDIA NIM API** with a structured grading prompt. The model returns a `correlation_score` (0.0–1.0) representing semantic similarity between the student's answer and the reference.
7. **Mark computation:** `awarded_marks = correlation_score × max_marks_for_question`. Sum across all questions for total.
8. **Reports:** Generate per-student report (PDF + JSON) and class-wide report (CSV). Professor can manually override any mark with a reason.

**Key design constraint:** All NV API calls must be async, semaphore-limited (max 5 concurrent), with exponential backoff retry (3 attempts). Grading runs as a background job with progress tracked in DB and polled by frontend.

---

#### Addition 2: Student Self-Service Portal

A new FastAPI service (Port 8004) where students log in with roll number + password (JWT auth, bcrypt hashed) and can:
- **Attendance tracking:** View per-class attendance %, session-wise breakdown (date, method: QR/Face/Manual), calendar heatmap, shortfall alert if < 75%.
- **Marks dashboard:** View all exam results, score vs class average, per-question breakdown with AI-generated feedback, download own grade report PDF.
- **Dispute center:** Raise an attendance dispute (wrong date, tech failure) or marks dispute (specific question, reason). Upload supporting evidence. Track dispute status (pending/reviewing/accepted/rejected). View professor's response.
- **Notifications:** Results published, dispute resolved, attendance corrections.

The professor dashboard gets new tabs for: Exam & Grading management, Dispute resolution, and Bulk student import via CSV.

---

### NVIDIA NIM API Details

Base URL: `https://integrate.api.nvidia.com/v1`  
Authentication: Bearer token in Authorization header  
Primary model for grading: `moonshotai/kimi-k2-5`  
Vision model for handwriting OCR: `meta/llama-3.2-90b-vision-instruct`  
The API is OpenAI-compatible — use the `/v1/chat/completions` endpoint.  
Use `"response_format": {"type": "json_object"}` for structured grading output.

---

### What I Need You to Produce

Generate **4 documents** with full technical depth. Do not summarize or be vague — provide concrete code patterns, data schemas, API contracts, and implementation steps that a developer could follow directly to build this system.

---

#### Document 1: `design.md` — System Architecture & Design

Include:
- Full microservice architecture diagram (ASCII)
- Service responsibility table (all 5 services, ports, roles)
- Complete grading workflow as a step-by-step flowchart (ASCII)
- Grading system prompt for Kimi K2.5 (exact text, JSON output schema)
- OCR routing strategy (decision tree: pdfplumber → tesseract → vision LLM)
- All new API endpoints for both Grading Engine and Student Portal with request/response schemas
- SQLModel data models for all new tables: `Exam`, `ExamQuestion`, `StudentAnswer`, `GradingJob`, `StudentUser`, `Dispute`, `Notification`
- Extended file system directory structure
- NV API client design (async, semaphore, retry)
- Frontend design description for new professor dashboard tabs and student portal tabs
- Security design table (auth, file validation, API keys, audit log)
- Performance considerations and mitigations
- Full `config.py` / `.env` variable list

#### Document 2: `skill.md` — Technical Reference

Include:
- All new Python packages with version pins and install commands
- Code patterns for: pdfplumber text extraction, pdf2image conversion, pytesseract OCR, NV API async client with tenacity retry, asyncio semaphore limiting, FastAPI BackgroundTasks pattern for long jobs, JWT auth with python-jose, bcrypt password hashing with passlib, reportlab PDF generation
- Complete OCR routing function implementation
- Complete answer segmentation function using Kimi K2.5
- Complete grading algorithm including professor override logic and class statistics computation
- Frontend JavaScript patterns for: progress bar polling, attendance heatmap rendering
- Full `requirements.txt` for v2

#### Document 3: `execution.md` — Phased Implementation Plan

Include:
- Explicit phase structure (Phase 0 through Phase 4) with time estimates per phase
- File-by-file creation order with specific implementation steps per file
- Ground rules (never break v1, additive DB migrations, feature flags)
- Exact shell commands for setup
- Test checkpoint at the end of each phase describing what to verify
- Integration test scenario descriptions
- Deployment checklist

#### Document 4: `todo.md` — Ordered Task Checklist

Include:
- Every implementation task as a checkbox item with a unique ID (e.g., P0-1, P1-3, P2-7)
- Organized by phase and sub-category
- Each task is atomic (completable in one focused session)
- A backlog section for post-MVP enhancements (WebSockets, mobile-responsive, Docker Compose, plagiarism detection, multi-language OCR, email notifications, rubric builder, analytics trends)

---

### Formatting & Quality Requirements

- Every code block must be in proper fenced code blocks with language tags
- ASCII diagrams must be aligned and readable
- API endpoint specs must include method, path, request body/params, and return shape
- Data models must be SQLModel Python classes, not just field names
- No hand-waving — if a pattern is described, show the actual Python/JS code
- Maintain consistency across all 4 documents (same port numbers, same model names, same table names)
- Use the exact NVIDIA NIM model slugs provided above

---

### Constraints

- Do not change existing v1 services (ports 8000–8002) structurally; only add new routes/tabs
- SQLite only (no PostgreSQL migration)
- All services use the same `main_app.db` file; enable WAL mode
- No external task queue (no Celery, no Redis) — use FastAPI BackgroundTasks only
- Frontend stays as Jinja2 HTML templates + vanilla JavaScript (no React/Vue)
- The student portal is a completely separate service (port 8004) with its own auth
