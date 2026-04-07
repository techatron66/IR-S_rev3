from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional


class Professor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password: str
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


class Exam(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    classroom_id: int = Field(foreign_key="classroom.id")
    professor_id: int = Field(foreign_key="professor.id")
    name: str
    exam_date: str
    status: str = Field(default="draft")  # draft | ocr_done | grading | published
    created_at: str
    questions: List["ExamQuestion"] = Relationship(back_populates="exam")
    answers: List["StudentAnswer"] = Relationship(back_populates="exam")

class ExamQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    q_number: int
    question_text: str
    max_marks: float
    reference_answer: Optional[str] = Field(default=None)
    exam: Exam = Relationship(back_populates="questions")
    student_answers: List["StudentAnswer"] = Relationship(back_populates="question")

class StudentAnswer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id")
    question_id: int = Field(foreign_key="examquestion.id")
    student_id: int = Field(foreign_key="student.id")
    raw_answer_text: str = Field(default="")
    closeness_pct: float = Field(default=0.0)    # 0–100 from Kimi
    awarded_marks: float = Field(default=0.0)    # closeness_pct/100 * max_marks
    ai_feedback: str = Field(default="")
    professor_override: Optional[float] = Field(default=None)
    override_reason: Optional[str] = Field(default=None)
    exam: Exam = Relationship(back_populates="answers")
    question: ExamQuestion = Relationship(back_populates="student_answers")

class GradingJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(foreign_key="exam.id", unique=True)
    status: str = Field(default="queued")    # queued | processing | completed | failed
    total_sheets: int = Field(default=0)
    processed_sheets: int = Field(default=0)
    error_log: Optional[str] = Field(default=None)
