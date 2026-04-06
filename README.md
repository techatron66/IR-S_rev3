# 🏛️ IR-S | AI-Powered Smart Attendance System

## Overview

**IR-S** is a modern, production-ready **microservice-based attendance management system** designed for university environments. It replaces traditional paper rolls with a **contactless, AI-powered solution** using facial recognition and QR codes.

The system eliminates manual attendance marking with an intelligent three-tier architecture: professors manage classes via a real-time dashboard, an AI engine processes biometric verification, and students check in via QR code + selfie authentication.

---

## 🏗️ System Architecture

The project uses a **Microservices Architecture** with three independent FastAPI applications running on separate ports:

| Service | Port | Purpose | Key Technology |
|---------|------|---------|-----------------|
| **Professor Dashboard** | 8000 | Central management hub for class administration and real-time attendance monitoring | FastAPI + Jinja2 + SQLModel |
| **AI Engine** | 8001 | Biometric processing - face verification using DeepFace FaceNet512 model | FastAPI + DeepFace + CUDA |
| **Student Portal** | 8002 | Lightweight mobile-friendly check-in interface with QR scanning and selfie capture | FastAPI + Jinja2 |

### Service Responsibilities

**1. Professor Dashboard (1_prof_dash.py)** - *Port 8000*
- Authentication and session management
- Class creation and student registration
- Live attendance monitoring with real-time updates
- Manual attendance toggle (override capability)
- CSV report generation and export
- Admin controls for system configuration

**Grading and Paper Correction** - *Route: `/grading` inside the Professor Dashboard*
- Create exams for a selected class
- Upload question papers and answer sheets
- Review AI-graded results per student and per question
- Override marks manually when needed
- Export final grades as CSV

**2. AI Engine (2_gpu_server.py)** - *Port 8001*
- Heavy computational AI workload isolated from main dashboard
- Facial recognition using DeepFace FaceNet512 embeddings
- Batch processing of student photos for training embeddings
- Real-time selfie verification (1-3 seconds per face)
- GPU acceleration support (NVIDIA CUDA) with CPU fallback
- API endpoints for face verification and database queries

**3. Student Portal (3_student_app.py)** - *Port 8002*
- QR code scanner interface (via mobile browser)
- Real-time selfie capture with device camera
- Instant biometric verification feedback
- Enrollment confirmation and status updates
- Lightweight design for low-bandwidth environments

---

## 🎨 Design System

The UI features a **modern Apple Keynote-inspired minimalist aesthetic** with frosted glass effects and smooth animations:

**Design Files:**
- `static/css/iris-design-system.css` - Complete CSS framework with variables, components, and animations (550+ lines)
- `static/js/iris-design-system.js` - Interactive utilities (modals, sidebar, toast notifications)

**Features:**
- ✨ Frosted glass effect (backdrop-filter blur)
- 🎬 Spring animations for smooth interactions
- 📱 Responsive sidebar navigation
- 🎨 System fonts (SF Pro Display, Segoe UI, -apple-system)
- ♿ WCAG accessible color palette
- 🔔 Built-in toast notification system

**Zero additional dependencies** - all design files included in the project.

---

## 📋 Directory Structure

```
IR-S_rev2/
│
├── 1_prof_dash.py                  # Professor dashboard (port 8000)
├── 2_gpu_server.py                 # AI engine / face verification (port 8001)
├── 3_student_app.py                # Student portal (port 8002)
├── grading_utils.py                # Shared grading helpers
├── models.py                       # SQLModel database schemas
├── migrate_db.py                   # Database bootstrap / migration helper
├── update_prof_dash.py             # Dashboard update helper
├── test_grading_system.py          # Grading system checks
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── main_app.db                     # SQLite database (created on first run)
│
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   └── nv_client.py
│
├── services/
│   ├── __init__.py
│   ├── 4_grading_engine.py         # Grading pipeline logic
│   ├── 5_student_portal.py         # Student portal support logic
│   └── grading_runner.py           # Background grading runner
│
├── static/
│   ├── css/
│   │   ├── iris-design-system.css   # Main dashboard design system
│   │   ├── grading.css
│   │   └── student_portal.css
│   └── js/
│       └── iris-design-system.js
│
├── templates/
│   ├── attendance.html
│   ├── disputes.html
│   ├── grading.html                # Grading / paper correction interface
│   ├── grading_confirm.html
│   ├── grading_results.html
│   ├── login.html
│   ├── manage.html
│   ├── register.html
│   ├── students.html
│   ├── students_import.html
│   ├── student_dashboard.html
│   ├── student_login.html
│   ├── grading/
│   │   ├── exam_create.html
│   │   ├── exam_detail.html
│   │   └── exams_list.html
│   └── student_portal/
│       ├── dashboard.html
│       ├── marks.html
│       ├── attendance.html
│       └── disputes.html
│
├── student_db/                     # Student training photos
├── prof_db/                        # Professor reports / exports
├── exam_db/                        # Uploaded exam papers
├── disputes/                       # Attendance dispute records
├── start.sh                        # Bash startup script
├── start_all.bat                   # Windows startup script
├── design.md
├── execution.md
├── todo.md
└── README.md
```

---

## 🚀 Installation & Setup

### Prerequisites

- **Python 3.9+** (test with `python --version`)
- **pip** package manager
- **Git** for version control
- **Webcam/Phone** for testing biometric features
- **4GB+ RAM** (8GB recommended for AI processing)
- **Optional:** NVIDIA GPU with CUDA toolkit (for 10x faster face recognition)

### Step 1: Get the Project

```bash
# Clone the repository, then open the project folder
cd IR-S_rev2
```

### Step 2: Create Virtual Environment

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Key dependencies:**
- FastAPI & Uvicorn (web framework)
- SQLModel (ORM database)
- DeepFace (face recognition AI)
- Python-multipart (form file uploads)
- Pillow (image processing)
- QRcode (QR generation)

### Step 4: Configure Environment

```bash
# Copy template to active configuration
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Network Configuration (for phone access)
PROF_SERVER=http://192.168.1.15:8000      # Your local IP
STUDENT_URL=http://192.168.1.15:8002      # Your local IP

# Database
DATABASE_URL=sqlite:///./main_app.db

# API Keys (if using external services)
NV_API_KEY=your_nvidia_api_key_here       # Optional
```

**Find your local IP:**

```bash
# Windows
ipconfig | findstr "IPv4"

# Mac/Linux
ifconfig | grep "inet " | grep -v 127.0.0.1
```

### Step 5: Start Services

Recommended startup order:

1. AI Engine on port 8001
2. Student Portal on port 8002
3. Professor Dashboard on port 8000

#### Windows (recommended)

Run the one-click launcher from the project root:

```bash
.\start_all.bat
```

What it does:
- Initializes the SQLite database if needed
- Starts the AI Engine
- Starts the Student Portal
- Starts the Professor Dashboard

#### macOS / Linux

```bash
bash ./start.sh
```

The shell script loads `.env`, activates `venv` if available, and starts the same three services.

#### Manual start (three terminals)

If you prefer to launch services yourself, open three terminals and run:

**Terminal 1 - AI Engine (start first):**
```bash
.\venv\Scripts\activate
uvicorn 2_gpu_server:app --host 0.0.0.0 --port 8001 --reload
```
✅ Wait for: `Uvicorn running on http://127.0.0.1:8001` or `http://0.0.0.0:8001`

**Terminal 2 - Student Portal:**
```bash
.\venv\Scripts\activate
uvicorn 3_student_app:app --host 0.0.0.0 --port 8002 --reload
```
✅ Wait for: `Uvicorn running on http://127.0.0.1:8002` or `http://0.0.0.0:8002`

**Terminal 3 - Professor Dashboard (start last):**
```bash
.\venv\Scripts\activate
uvicorn 1_prof_dash:app --host 0.0.0.0 --port 8000 --reload
```
✅ Wait for: `Uvicorn running on http://127.0.0.1:8000` or `http://0.0.0.0:8000`

### Step 6: Access the Application

- **Local testing:** Open `http://127.0.0.1:8000`
- **Mobile/phone access:** Open `http://YOUR_LOCAL_IP:8000` (use IP from `.env`)
- **Grading page:** Open `http://127.0.0.1:8000/grading` after logging in

**Default credentials (if not provided):**
- Register a new professor account first
- Set student credentials via the dashboard

---

## Workflow Guide

1. **Class Management**
  - Create a class for a subject and batch.
  - Register students with roll number, name, and reference photos.
  - Upload a group photo to trigger face verification.

2. **Live Attendance**
  - Project the QR code on a screen.
  - Students scan the QR, take a selfie, and get verified.
  - The attendance table updates live.
  - Use manual override switches if you need to correct a row.
  - Export the daily attendance report as CSV.

3. **Grading / Paper Correction**
  - Open the Grading page from the dashboard sidebar.
  - Select a class, then create a new exam.
  - Upload the question paper and answer sheets.
  - Start grading and wait for the AI pipeline to finish.
  - Review results, open per-question breakdowns, override marks if required, and export CSV.

---

## What This Application Does

IR-S is split into three user-facing flows:

- **Professor Dashboard:** manage classes, register students, view live attendance, and run grading.
- **AI Engine:** handle heavy face verification and photo processing without slowing down the dashboard.
- **Student Portal:** let students scan a QR code, take a selfie, and check in from a phone browser.

The grading module is not a separate server. It is part of the professor dashboard and uses the shared grading workflow behind `/grading`, `/grading/results/{exam_id}`, and `/grading/override`.

---

## Database Structure

The system uses SQLModel (SQLite) for data and a structured file system for images.

```
attendance/
│
├── student_db/                 <-- Training Photos Storage
│   └── [Class_Name]/
│       └── stu_[Roll_No]/      <-- Individual Student Photos
│
├── prof_db/                    <-- Reports Storage
│   └── prof_[ID]/
│       └── [Class_Name]/       <-- Generated CSV Reports
│
├── main_app.db                 <-- SQLite Database File
├── templates/                  <-- HTML UI Files
└── static/                     <-- Assets Folder
```

---

## What's New in This Version

### UI/UX Enhancements
- **Modern Design System**: Shared dashboard styling across login, class management, attendance, and grading pages
- **Responsive Layouts**: Sidebar navigation, card-based components, and mobile-friendly forms
- **Toast Notifications**: Real-time feedback system for user actions
- **Keyboard Navigation**: Enhanced accessibility with shortcuts and keyboard controls

### Updated Templates
- `login.html` and `register.html` - Card-centered authentication interface
- `student_login.html` - Selfie check-in page for students
- `attendance.html` - Live attendance dashboard
- `manage.html` - Class and student management forms
- `grading.html` and `grading_results.html` - Grading and paper correction pages

### New Design System Files
- `static/css/iris-design-system.css` - Complete CSS framework
- `static/js/iris-design-system.js` - Component utilities and interactive features

---

## Troubleshooting

**Q: Services fail to start with exit code 1.**
- Fix 1: Verify all dependencies are installed: `pip install -r requirements.txt`
- Fix 2: Check if ports 8000, 8001, 8002 are already in use:
  ```bash
  # Windows
  netstat -ano | findstr ":8000"
  # Mac/Linux
  lsof -i :8000
  ```
- Fix 3: Ensure `.env` exists and has the correct configuration: `cp .env.example .env`
- Fix 4: Try starting services with verbose output:
  ```bash
  uvicorn 1_prof_dash:app --host 0.0.0.0 --port 8000 --reload
  ```

**Q: The QR Code link says "Site Can't Be Reached" on mobile.**
- Fix 1: Ensure both laptop and phone are on the same Wi-Fi.
- Fix 2: Use a mobile hotspot if your router blocks local traffic.
- Fix 3: Turn off Windows Firewall temporarily.
- Fix 4: Verify you are using the correct local IP from `.env` configuration.

**Q: "Internal Server Error" when registering.**
- Fix: You might be missing a library or have a corrupted DB.
  - Run `pip install python-multipart`.
  - Delete `main_app.db`.
  - Restart `1_prof_dash.py` to recreate the database.

**Q: Design system styles not loading (unstyled page).**
- Fix 1: Clear browser cache (Ctrl+Shift+Delete).
- Fix 2: Check the browser console for 404 errors on CSS/JS files.
- Fix 3: Verify `static/css/iris-design-system.css` and `static/js/iris-design-system.js` exist.
- Fix 4: Ensure the server is running and accessible at the configured URL.

**Q: The AI is slow.**
- Fix: Face recognition is heavy. On a CPU, it may take 1-3 seconds per verification. For faster results, run on a machine with an NVIDIA GPU.