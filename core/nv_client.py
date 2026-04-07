"""
Async NVIDIA NIM API client with semaphore limiting and automatic retry.
"""
import asyncio
import base64
import json
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from core.config import settings


class NVAPIClient:
    """
    Async client for NVIDIA NIM API.
    - Semaphore-limited: max MAX_CONCURRENT_NV_CALLS concurrent requests
    - Automatic retry: 3 attempts with exponential backoff on 429/500
    - Supports text completion (Kimi K2.5) and vision OCR (LLaMA 3.2 Vision)
    """

    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_NV_CALLS)
        self.headers = {
            "Authorization": f"Bearer {settings.NV_API_KEY}",
            "Content-Type": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    )
    async def _post(self, payload: dict) -> str:
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.NV_API_BASE}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

    async def chat_completion(
        self,
        messages: list,
        model: str = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        payload = {
            "model": model or settings.KIMI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return await self._post(payload)

    async def vision_ocr(self, image_b64: str, prompt: str = None) -> str:
        """
        Use vision LLM to transcribe handwritten exam sheet images.
        image_b64: base64-encoded JPEG image string
        """
        text_prompt = prompt or (
            "Transcribe ALL handwritten text from this exam answer sheet exactly as written. "
            "Preserve question number markers (Q1, Q2, 1., 2., etc.) as headers. "
            "Return plain text only, no markdown, no commentary."
        )
        payload = {
            "model": settings.VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                        {"type": "text", "text": text_prompt},
                    ],
                }
            ],
            "max_tokens": 4096,
        }
        return await self._post(payload)


# Module-level singleton
nv_client = NVAPIClient()
