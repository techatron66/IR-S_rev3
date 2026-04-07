import sys

with open("d:/projets/IR-S_rev2/1_prof_dash.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = lines[:376]

# But first we modify the imports
import_str = "from grading_utils import ocr_pdf_to_text, extract_questions_from_text, grade_student_sheet\n"
new_lines.insert(25, import_str)

code_to_add = """
# =============================================
# GRADING FEATURE ROUTES
# =============================================

@app.get("/grading", response_class=HTMLResponse)
def grading_page(request: Request, class_id: int = None,
                 prof: Professor = Depends(get_current_prof),
                 session: Session = Depends(get_session)):
    if not prof:
        return RedirectResponse("/login")
    classes = prof.classes
    selected_class = session.get(ClassRoom, class_id) if class_id else None
    exams = []
    if selected_class and selected_class.professor_id == prof.id:
        exams = session.exec(
            select(Exam).where(Exam.classroom_id == class_id)
        ).all()
        for exam in exams:
            job = session.exec(
                select(GradingJob).where(GradingJob.exam_id == exam.id)
            ).first()
            exam._job = job
    return templates.TemplateResponse(request, name="grading.html", context={
        "prof": prof,
        "classes": classes,
        "selected_class": selected_class,
        "selected_class_id": class_id,
        "exams": exams
    })

@app.post("/grading/upload-question-paper")
async def upload_question_paper(
    class_id: int = Form(...),
    exam_name: str = Form(...),
    exam_date: str = Form(...),
    question_paper: UploadFile = File(...),
    prof: Professor = Depends(get_current_prof),
    session: Session = Depends(get_session)
):
    if not prof:
        return RedirectResponse("/login")
    
    exam = Exam(
        classroom_id=class_id,
        professor_id=prof.id,
        name=exam_name,
        exam_date=exam_date,
        status="draft",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    session.add(exam)
    session.commit()
    session.refresh(exam)
    
    os.makedirs(EXAM_DIR, exist_ok=True)
    exam_folder = os.path.join(EXAM_DIR, str(exam.id))
    os.makedirs(exam_folder, exist_ok=True)
    
    _, ext = os.path.splitext(question_paper.filename)
    qp_path = os.path.join(exam_folder, f"question_paper{ext}")
    pdf_bytes = await question_paper.read()
    with open(qp_path, "wb") as f:
        f.write(pdf_bytes)
        
    raw_text = await ocr_pdf_to_text(pdf_bytes)
    extracted_questions = await extract_questions_from_text(raw_text)
    
    return templates.TemplateResponse(request=None, name="grading_confirm.html", context={
        "request": {},
        "exam": exam,
        "extracted_questions": extracted_questions,
        "class_id": class_id
    })

@app.post("/grading/confirm-questions")
async def confirm_questions(
    exam_id: int = Form(...),
    q_texts: list[str] = Form(...),
    q_marks: list[float] = Form(...),
    q_refs: list[str] = Form(...),
    answer_sheets: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    prof: Professor = Depends(get_current_prof),
    session: Session = Depends(get_session)
):
    if not prof:
        return RedirectResponse("/login")
        
    exam = session.get(Exam, exam_id)
    if not exam:
        return RedirectResponse("/grading")

    for i, (text, marks, ref) in enumerate(zip(q_texts, q_marks, q_refs)):
        if not text.strip(): continue
        q = ExamQuestion(
            exam_id=exam.id,
            q_number=i+1,
            question_text=text.strip(),
            max_marks=float(marks),
            reference_answer=ref.strip() if ref.strip() else None
        )
        session.add(q)
    session.commit()
    
    sheet_data = []
    for sheet in answer_sheets:
        if not sheet.filename: continue
        roll = os.path.splitext(sheet.filename)[0]
        data = await sheet.read()
        sheet_data.append((roll, data))
        
    job = GradingJob(exam_id=exam.id, status="queued", total_sheets=len(sheet_data))
    exam.status = "grading"
    session.add(job)
    session.add(exam)
    session.commit()
    session.refresh(job)
    
    background_tasks.add_task(_run_grading_job, job.id, exam.id, sheet_data)
    return RedirectResponse(f"/grading?class_id={exam.classroom_id}", status_code=303)

async def _run_grading_job(job_id: int, exam_id: int, sheet_data: list[tuple[str, bytes]]):
    from sqlmodel import Session, select, create_engine
    engine2 = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    
    with Session(engine2) as s:
        job = s.get(GradingJob, job_id)
        exam = s.get(Exam, exam_id)
        questions = s.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
        job.status = "processing"
        s.add(job)
        s.commit()

    errors = []
    for roll_number, pdf_bytes in sheet_data:
        try:
            results = await grade_student_sheet(pdf_bytes, questions, roll_number)
            with Session(engine2) as s:
                student = s.exec(
                    select(Student).where(Student.classroom_id == exam.classroom_id,
                                          Student.roll_number == roll_number)
                ).first()
                if not student:
                    errors.append(f"{roll_number}: not found in class")
                    continue
                    
                old = s.exec(select(StudentAnswer).where(
                    StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == student.id)).all()
                for a in old: s.delete(a)
                
                for r in results:
                    s.add(StudentAnswer(
                        exam_id=exam_id, question_id=r["question_id"], student_id=student.id,
                        raw_answer_text=r["raw_answer_text"][:3000],
                        closeness_pct=r["closeness_pct"], awarded_marks=r["awarded_marks"],
                        ai_feedback=r["feedback"]
                    ))
                s.commit()
        except Exception as e:
            errors.append(f"{roll_number}: {str(e)[:200]}")
        finally:
            with Session(engine2) as s:
                j = s.get(GradingJob, job_id)
                j.processed_sheets += 1
                s.add(j)
                s.commit()

    with Session(engine2) as s:
        j = s.get(GradingJob, job_id)
        ex = s.get(Exam, exam_id)
        j.status = "failed" if len(errors) == len(sheet_data) else "completed"
        j.error_log = "\\n".join(errors) if errors else None
        ex.status = "published"
        s.add(j)
        s.add(ex)
        s.commit()

@app.get("/api/grading/job/{exam_id}")
def get_grading_job(exam_id: int, session: Session = Depends(get_session)):
    job = session.exec(select(GradingJob).where(GradingJob.exam_id == exam_id)).first()
    if not job:
        return JSONResponse({"status": "not_found", "progress": 0, "processed": 0, "total": 0})
    pct = int((job.processed_sheets / max(1, job.total_sheets)) * 100) if job.total_sheets > 0 else 0
    return JSONResponse({
        "status": job.status,
        "progress": pct,
        "processed": job.processed_sheets,
        "total": job.total_sheets,
        "error_log": job.error_log
    })

@app.get("/grading/results/{exam_id}", response_class=HTMLResponse)
def grading_results(request: Request, exam_id: int,
                    prof: Professor = Depends(get_current_prof),
                    session: Session = Depends(get_session)):
    if not prof:
        return RedirectResponse("/login")
    exam = session.get(Exam, exam_id)
    if not exam or exam.professor_id != prof.id:
        return RedirectResponse("/grading")
    questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    students = session.exec(select(Student).where(Student.classroom_id == exam.classroom_id)).all()
    
    results = []
    for s in students:
        answers = session.exec(select(StudentAnswer).where(
            StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == s.id)).all()
        ans_map = {a.question_id: a for a in answers}
        breakdown = []
        total = 0.0
        max_total = sum(q.max_marks for q in questions)
        for q in questions:
            a = ans_map.get(q.id)
            if a:
                awarded = a.professor_override if a.professor_override is not None else a.awarded_marks
                breakdown.append({
                    "q_number": q.q_number,
                    "question_text": q.question_text,
                    "max_marks": q.max_marks,
                    "awarded": awarded,
                    "closeness_pct": a.closeness_pct,
                    "feedback": a.ai_feedback,
                    "answer_id": a.id,
                    "overridden": a.professor_override is not None
                })
                total += awarded
            else:
                breakdown.append({
                    "q_number": q.q_number,
                    "question_text": q.question_text,
                    "max_marks": q.max_marks,
                    "awarded": 0.0,
                    "closeness_pct": 0.0,
                    "feedback": "Not graded",
                    "answer_id": None,
                    "overridden": False
                })
        results.append({
            "roll": s.roll_number,
            "name": s.name,
            "student_id": s.id,
            "total": round(total, 2),
            "max_total": max_total,
            "percentage": round((total / max(0.001, max_total)) * 100, 1),
            "breakdown": breakdown
        })
        
    results.sort(key=lambda x: x["total"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
        
    scores = [r["total"] for r in results if r["total"] > 0]
    stats = {}
    if scores:
        stats = {
            "mean": round(sum(scores) / len(scores), 2),
            "highest": max(scores),
            "lowest": min(scores),
            "pass_count": sum(1 for s in scores if s >= 0.4 * results[0]["max_total"]) if results else 0,
            "total_students": len(students)
        }
    classroom = session.get(ClassRoom, exam.classroom_id)
    return templates.TemplateResponse(request, name="grading_results.html", context={
        "prof": prof, "exam": exam, "classroom": classroom, "questions": questions, "results": results, "stats": stats
    })

@app.post("/api/grading/override")
async def override_mark(
    answer_id: int = Form(...),
    new_marks: float = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
    prof: Professor = Depends(get_current_prof)
):
    if not prof: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    answer = session.get(StudentAnswer, answer_id)
    if not answer: return JSONResponse({"error": "Answer not found"}, status_code=404)
    q = session.get(ExamQuestion, answer.question_id)
    new_m = max(0.0, min(float(new_marks), q.max_marks))
    answer.professor_override = new_m
    answer.override_reason = reason
    session.add(answer)
    session.commit()
    return JSONResponse({"ok": True, "new_marks": new_m})

@app.get("/grading/export/{exam_id}/csv")
def export_results_csv(exam_id: int, prof: Professor = Depends(get_current_prof), session: Session = Depends(get_session)):
    if not prof: return RedirectResponse("/login")
    exam = session.get(Exam, exam_id)
    questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)).all()
    students = session.exec(select(Student).where(Student.classroom_id == exam.classroom_id)).all()
    
    output = StringIO()
    writer = csv.writer(output)
    header = ["Roll No", "Name", "Total", "Max Total", "Percentage"] + [f"Q{q.q_number} ({q.max_marks})" for q in questions]
    writer.writerow(header)
    
    for s in students:
        answers = session.exec(select(StudentAnswer).where(StudentAnswer.exam_id == exam_id, StudentAnswer.student_id == s.id)).all()
        ans_map = {a.question_id: a for a in answers}
        row = [s.roll_number, s.name]
        total = 0.0
        max_total = sum(q.max_marks for q in questions)
        per_q = []
        for q in questions:
            a = ans_map.get(q.id)
            awarded = a.professor_override if (a and a.professor_override is not None) else (a.awarded_marks if a else 0.0)
            total += awarded
            per_q.append(round(awarded, 2))
        row += [round(total, 2), max_total, round((total / max(0.001, max_total)) * 100, 1)] + per_q
        writer.writerow(row)
        
    output.seek(0)
    csv_path = os.path.join(EXAM_DIR, f"{exam.name.replace(' ', '_')}_results.csv")
    with open(csv_path, "w") as f: f.write(output.getvalue())
    return FileResponse(csv_path, filename=f"{exam.name}_results.csv", media_type="text/csv")

@app.get("/api/student-results/{roll_number}/{class_id}")
def get_student_results_api(roll_number: str, class_id: int, session: Session = Depends(get_session)):
    student = session.exec(select(Student).where(
        Student.classroom_id == class_id, Student.roll_number == roll_number)).first()
    if not student: return JSONResponse({"error": "Student not found"}, status_code=404)
    
    exams = session.exec(select(Exam).where(Exam.classroom_id == class_id, Exam.status == "published")).all()
    results = []
    
    for exam in exams:
        questions = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)).all()
        answers = session.exec(select(StudentAnswer).where(
            StudentAnswer.exam_id == exam.id, StudentAnswer.student_id == student.id)).all()
        ans_map = {a.question_id: a for a in answers}
        max_total = sum(q.max_marks for q in questions)
        breakdown = []
        total = 0.0
        for q in questions:
            a = ans_map.get(q.id)
            awarded = a.professor_override if (a and a.professor_override is not None) else (a.awarded_marks if a else 0.0)
            feedback = a.ai_feedback if a else "Not graded yet"
            total += awarded
            breakdown.append({
                "q_number": q.q_number, "question_text": q.question_text,
                "max_marks": q.max_marks, "awarded": round(awarded, 2),
                "closeness_pct": a.closeness_pct if a else 0.0,
                "feedback": feedback
            })
            
        all_ans = session.exec(select(StudentAnswer).where(StudentAnswer.exam_id == exam.id)).all()
        if all_ans:
            by_student = {}
            for a in all_ans:
                aw = a.professor_override if a.professor_override is not None else a.awarded_marks
                by_student[a.student_id] = by_student.get(a.student_id, 0) + aw
            class_avg = round(sum(by_student.values()) / len(by_student), 2) if by_student else 0.0
            sorted_scores = sorted(by_student.values(), reverse=True)
            rank = sorted_scores.index(by_student.get(student.id, 0)) + 1 if student.id in by_student else None
        else:
            class_avg = 0.0
            rank = None
            
        results.append({
            "exam_id": exam.id, "exam_name": exam.name, "exam_date": exam.exam_date,
            "total": round(total, 2), "max_total": max_total,
            "percentage": round((total / max(0.001, max_total)) * 100, 1),
            "class_average": class_avg, "rank": rank, "breakdown": breakdown
        })
        
    all_att = session.exec(select(Attendance).where(
        Attendance.classroom_id == class_id, Attendance.student_id == student.id)).all()
    total_days = len(set(a.date for a in all_att)) if all_att else 0
    present_days = sum(1 for a in all_att if a.status == "Present") if all_att else 0
    
    return JSONResponse({
        "student": {"roll": student.roll_number, "name": student.name},
        "attendance": {
            "total_sessions": total_days,
            "present": present_days,
            "percentage": round((present_days / max(1, total_days)) * 100, 1) if total_days > 0 else 0.0
        },
        "exams": results
    })

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

with open("d:/projets/IR-S_rev2/1_prof_dash_new.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
    f.write(code_to_add)

import shutil
shutil.move("d:/projets/IR-S_rev2/1_prof_dash_new.py", "d:/projets/IR-S_rev2/1_prof_dash.py")
