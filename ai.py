import asyncio
from pathlib import Path

from google import genai
from google.genai import types

# Bundan katta fayl so'rov ichida emas, Files API orqali yuboriladi
INLINE_LIMIT_BYTES = 15 * 1024 * 1024

AV_PROMPT = """Bu xabardagi nutqni so'zma-so'z yozib ber.
- Asl tilida yoz, tarjima qilma, qisqartirma va o'zingdan hech narsa qo'shma.
- Eshitilmagan joyni [noaniq] deb belgila.
- Faqat matnni qaytar. Nutq bo'lmasa, faqat [nutq yo'q] deb yoz."""

IMAGE_PROMPT = """Bu rasmdagi barcha matnni asl tilida, tarjimasiz va o'zgartirmasdan yozib ber.
Agar rasmda matndan tashqari muhim narsa bo'lsa (jadval, chizma, sxema, joy), oxirida
"Tavsif:" deb o'zbek tilida qisqa yoz. Rasmda yo'q narsani to'qima. Faqat natijani qaytar."""

PDF_PROMPT = """Bu hujjatdagi barcha matnni asl tilida, tarjimasiz va o'zgartirmasdan yozib ber.
Faqat matnni qaytar."""


def can_read(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    return mime_type.startswith(("image/", "audio/", "video/")) or mime_type == "application/pdf"


def _prompt_for(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return IMAGE_PROMPT
    if mime_type == "application/pdf":
        return PDF_PROMPT
    return AV_PROMPT


class GeminiReader:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=300_000)
        )
        self._model = model

    async def read_file(self, path: Path, mime_type: str) -> str:
        prompt = _prompt_for(mime_type)
        if path.stat().st_size <= INLINE_LIMIT_BYTES:
            part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)
            return await self._generate(part, prompt)

        uploaded = await self._client.aio.files.upload(
            file=path, config=types.UploadFileConfig(mime_type=mime_type)
        )
        try:
            while uploaded.state and uploaded.state.name == "PROCESSING":
                await asyncio.sleep(3)
                uploaded = await self._client.aio.files.get(name=uploaded.name)
            if uploaded.state and uploaded.state.name == "FAILED":
                raise RuntimeError("Gemini faylni qayta ishlay olmadi")
            return await self._generate(uploaded, prompt)
        finally:
            await self._client.aio.files.delete(name=uploaded.name)

    async def _generate(self, content, prompt: str) -> str:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[content, prompt],
            config=types.GenerateContentConfig(temperature=0),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini bo'sh javob qaytardi")
        return text
