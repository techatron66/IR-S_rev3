"""
IRIS v2 SQLModel table definitions.
Extends v1 tables (Professor, ClassRoom, Student, Attendance) with new v2 tables.
NOTE: v1 uses 'ClassRoom' and 'roll_number' — kept as-is for backward compat.
"""
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime


# ─── EXISTING v1 TABLES (preserved exactly, referenced by 1_prof_dash.py) ────

class Professor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password: str  # plain-text for v1 compat

    classes: List["ClassRoom"] = Relationship(back_populates="professor")


class ClassRoom(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    batch: str
    professor_id: int = Field(foreign_key="professor.id")

    professor: Professor = Relationship(back_populates="classes")
    students: List["Student"] = Relationship(back_populates="classroom")
    attendance_records: List["Attendance"] = Relationship(back_populates="classroom")


class Student(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    roll_number: str
    name: str
    classroom_id: int = Field(foreign_key="classroom.id")
    folder_path: str

    classroom: ClassRoom = Relationship(back_populates="students")
    attendance_records: List["Attendance"] = Relationship(back_populates="student")


class Attendance(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str
    time: str
    method: str  # "Selfie" | "ClassPhoto" | "Manual"
    status: str

    student_id: int = Field(foreign_key="student.id")
    classroom_id: int = Field(foreign_key="classroom.id")

    student: Student = Relationship(back_populates="attendance_records")
    classroom: ClassRoom = Relationship(back_populates="attendance_records")


# ─── NEW v2 TABLES ────────────────────────────────────────────────────────────

class Exam(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    class_id: int = Field(foreign_key="classroom.id")
    exam_name: str
    exam_date: str
    total_marks: float = 0.0
    status: str = "draft"           # draft | ready | grading | completed | published
    question_paper_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExamQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    q_number: int
    question_text: str
    max_marks: float
    reference_answer: Optional[str] = None


class StudentAnswer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    student_id: int = Field(foreign_key="student.id")
    question_id: int = Field(foreign_key="examquestion.id")
    raw_ocr_text: Optional[str] = None
    correlation_score: float = 0.0
    awarded_marks: float = 0.0
    ai_rationale: Optional[str] = None
    ai_feedback: Optional[str] = None
    missing_concepts: Optional[str] = None  # JSON array string
    professor_override: Optional[float] = None
    override_reason: Optional[str] = None
    status: str = "pending"         # pending | graded | failed | manual_review


class GradingJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    status: str = "queued"          # queued | processing | completed | failed | paused
    total_sheets: int = 0
    processed_sheets: int = 0
    failed_sheets: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_log: Optional[str] = None


class StudentUser(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    roll_no: str = Field(unique=True)
    name: str
    email: Optional[str] = None
    password_hash: str
    class_ids: str = "[]"           # JSON array of classroom IDs (int)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Dispute(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="studentuser.id")
    type: str                       # attendance | marks
    ref_id: int                     # session_id or student_answer_id
    reason: str
    evidence_path: Optional[str] = None
    status: str = "pending"         # pending | reviewing | accepted | rejected
    professor_response: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_type: str                  # professor | student
    user_id: int
    message: str
    link: Optional[str] = None
    read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    action: str
    actor_type: str                 # professor | student | system
    actor_id: int
    target_type: str
    target_id: int
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
