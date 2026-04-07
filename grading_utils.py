"""
grading_utils.py
All OCR and AI grading logic for IRIS v2.
Uses NVIDIA NIM API — Kimi K2.5 for text grading, LLaMA Vision for OCR.
"""
import os, io, base64, json, asyncio
import httpx
from pdf2image import convert_from_bytes
import pdfplumber
from dotenv import load_dotenv

load_dotenv()

NV_API_KEY  = os.getenv("NV_API_KEY", "")
NV_BASE     = os.getenv("NV_API_BASE", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL  = os.getenv("KIMI_MODEL",  "moonshotai/kimi-k2-5")
VISION_MODEL = os.getenv("VISION_MODEL", "meta/llama-3.2-90b-vision-instruct")

_sem = asyncio.Semaphore(4)   # max 4 concurrent NV API calls

def HEADERS():
    return {
        "Authorization": f"Bearer {NV_API_KEY}",
        "Content-Type": "application/json"
    }

async def ocr_pdf_to_text(pdf_bytes: bytes) -> str:
    from PIL import Image
    is_pdf = pdf_bytes.startswith(b"%PDF")
    
    if is_pdf:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                if len(text.strip()) > 80:
                    return text
        except Exception:
            pass
            
        try:
            images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "poppler", "Library", "bin"))
        except Exception as e:
            return f"[OCR Error: PDF conversion failed: {str(e)}]"
    else:
        try:
            images = [Image.open(io.BytesIO(pdf_bytes))]
        except Exception as e:
            return f"[OCR Error: Image load failed: {str(e)}]"
            
    full_text = ""
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        for img in images:
            b = io.BytesIO()
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            img.save(b, format="JPEG")
            b64 = base64.b64encode(b.getvalue()).decode("utf-8")
            
            payload = {
                "model": VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": "Transcribe all text from this document page exactly as written. Preserve question numbers and structure. Return plain text only."}
                    ]
                }],
                "max_tokens": 2048
            }
            
            async with _sem:
                resp = await client.post(f"{NV_BASE}/chat/completions", headers=HEADERS(), json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    full_text += data["choices"][0]["message"]["content"] + "\n"
                else:
                    full_text += f"[OCR Error: {resp.status_code}]\n"
                    
    return full_text

async def extract_questions_from_text(raw_text: str) -> list[dict]:
    payload = {
        "model": KIMI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a question paper parser. Extract all questions from the provided text. Return ONLY a JSON array. Each element: {\"q_number\": int, \"question_text\": str}. Preserve the original question wording exactly. If a question has sub-parts (a, b, c), treat the whole question as one entry."
            },
            {
                "role": "user",
                "content": f"Extract all questions from this text:\n\n{raw_text}"
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with _sem:
            try:
                resp = await client.post(f"{NV_BASE}/chat/completions", headers=HEADERS(), json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        return parsed
                    elif isinstance(parsed, dict) and "questions" in parsed:
                        return parsed["questions"]
                    else:
                        raise ValueError("Unexpected JSON structure")
            except Exception as e:
                return [{"q_number": 1, "question_text": raw_text[:500]}]
    return [{"q_number": 1, "question_text": raw_text[:500]}]

async def grade_answer(question_text: str, student_answer: str, max_marks: float, reference_answer: str | None = None) -> dict:
    ref_txt = f"Reference Answer: {reference_answer}" if reference_answer else "No reference answer provided — use your subject knowledge."
    user_msg = f"Question: {question_text}\n{ref_txt}\nStudent Answer: {student_answer if student_answer.strip() else '[No answer written]'}\nMaximum Marks: {max_marks}\n\nReturn JSON:\n{{\n  \"closeness_pct\": <integer 0-100>,\n  \"awarded_marks\": <float, = closeness_pct/100 * max_marks, rounded to 2 decimal places>,\n  \"feedback\": \"<one sentence of constructive feedback for the student>\"\n}}"
    
    payload = {
        "model": KIMI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert exam grader. Your job is to score a student's answer to a question on a scale of 0 to 100, where 100 means the answer fully and correctly addresses the question. Judge based on conceptual correctness, completeness, and relevance. If a reference answer is provided, use it as a guide but also accept other valid approaches. Return ONLY valid JSON."
            },
            {
                "role": "user",
                "content": user_msg
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with _sem:
            try:
                resp = await client.post(f"{NV_BASE}/chat/completions", headers=HEADERS(), json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    res = json.loads(content)
                    cpct = float(res.get("closeness_pct", 0))
                    cpct = max(0.0, min(100.0, cpct))
                    am = float(res.get("awarded_marks", 0.0))
                    am = max(0.0, min(max_marks, am))
                    return {
                        "closeness_pct": cpct,
                        "awarded_marks": round(am, 2),
                        "feedback": str(res.get("feedback", ""))
                    }
            except Exception as e:
                pass
    return {"closeness_pct": 0.0, "awarded_marks": 0.0, "feedback": "Could not grade automatically."}

async def grade_student_sheet(pdf_bytes: bytes, questions: list, roll_number: str) -> list[dict]:
    raw_text = await ocr_pdf_to_text(pdf_bytes)
    
    payload = {
        "model": KIMI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You split exam answer sheets into per-question sections. Return ONLY valid JSON with integer string keys."
            },
            {
                "role": "user",
                "content": f"Split this answer sheet into {len(questions)} sections by question number markers. Keys are question numbers as strings.\n\nAnswer sheet:\n{raw_text[:5000]}"
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    answers_dict = {}
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with _sem:
            try:
                resp = await client.post(f"{NV_BASE}/chat/completions", headers=HEADERS(), json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    answers_dict = json.loads(content)
            except Exception as e:
                pass

    if not answers_dict:
        lines = raw_text.split('\n')
        chunk_size = max(1, len(lines) // len(questions))
        for i, q in enumerate(questions):
            answers_dict[str(q.q_number)] = "\n".join(lines[i*chunk_size:(i+1)*chunk_size])
            
    tasks = []
    for q in questions:
        ans_text = answers_dict.get(str(q.q_number), "")
        tasks.append(grade_answer(q.question_text, ans_text, q.max_marks, getattr(q, "reference_answer", None)))
        
    graded_results = await asyncio.gather(*tasks)
    
    final_results = []
    for q, graded in zip(questions, graded_results):
        ans_text = answers_dict.get(str(q.q_number), "")
        final_results.append({
            "question_id": q.id,
            "raw_answer_text": ans_text,
            "closeness_pct": graded["closeness_pct"],
            "awarded_marks": graded["awarded_marks"],
            "feedback": graded["feedback"]
        })
        
    return final_results
