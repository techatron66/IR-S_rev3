import asyncio
import importlib.util

def get_grading_engine():
    spec = importlib.util.spec_from_file_location("grading_engine", "services/4_grading_engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

async def run_grading_pipeline(job_id: int, exam_id: int, sheets: list):
    m = get_grading_engine()
    await m.run_grading_pipeline(job_id, exam_id, sheets)
