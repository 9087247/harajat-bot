import asyncio
import logging
import mimetypes
import re
from collections.abc import Mapping
from pathlib import Path

import asyncpg
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import db
from ai import GeminiReader, can_read
from config import MEDIA_DIR, Config
from document import build_document, month_bounds, month_path

log = logging.getLogger(__name__)

PREVIEW_CHARS = 500


def _suffix(row: Mapping) -> str:
    suffix = Path(row["file_name"] or "").suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
        suffix = mimetypes.guess_extension(row["mime_type"] or "") or ".bin"
    return suffix


class Worker:
    """Saqlangan xabarlarni navbat bilan qayta ishlaydi. Navbat bazada, shuning uchun
    bot qayta ishga tushsa ham xabar yo'qolmaydi."""

    def __init__(self, bot: Bot, pool: asyncpg.Pool, reader: GeminiReader, config: Config):
        self._bot = bot
        self._pool = pool
        self._reader = reader
        self._config = config
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            self._wake.clear()
            try:
                for row in await db.due_messages(self._pool):
                    await self._process(row)
            except Exception:
                log.exception("Navbatni o'qishda xato")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    async def _process(self, row: asyncpg.Record) -> None:
        try:
            ai_text = await self._read_content(row)
        except Exception as error:
            log.exception("Xabar #%s qayta ishlanmadi", row["id"])
            gave_up = await db.mark_error(self._pool, row["id"], f"{type(error).__name__}: {error}")
            if gave_up:
                warning = await self._rebuild_month(row)
                await self._update_ack(
                    row,
                    "⚠️ Xabar saqlandi va hujjatga kiritildi, lekin matnini o'qib bo'lmadi. "
                    "Keyinroq /qayta yuboring." + warning,
                )
            return

        await db.mark_done(self._pool, row["id"], ai_text)
        warning = await self._rebuild_month(row)
        text = "✅ Hujjatga qo'shildi." + warning
        if row["note"]:
            text += f"\n⚠️ {row['note']}"
        if ai_text:
            preview = ai_text[:PREVIEW_CHARS] + ("…" if len(ai_text) > PREVIEW_CHARS else "")
            text += f"\n\n{preview}"
        await self._update_ack(row, text)

    async def _read_content(self, row: asyncpg.Record) -> str | None:
        if not row["file_id"]:
            return None

        path = Path(row["file_path"]) if row["file_path"] else None
        if path is None or not path.exists():
            local_month = row["sent_at"].astimezone(self._config.timezone)
            path = MEDIA_DIR / f"{local_month:%Y-%m}" / f"{row['id']}{_suffix(row)}"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self._bot.download(row["file_id"], destination=path)
            await db.set_file_path(self._pool, row["id"], str(path))
            row = {**row, "file_path": str(path)}

        if can_read(row["mime_type"]):
            return await self._reader.read_file(path, row["mime_type"])
        return None

    async def _rebuild_month(self, row: asyncpg.Record) -> str:
        """Oy hujjatini bazadan qayta yig'adi. Foydalanuvchi uchun ogohlantirish qaytaradi."""
        tz = self._config.timezone
        start, end = month_bounds(row["sent_at"], tz)
        path = month_path(row["sent_at"], tz)
        try:
            rows = await db.messages_between(self._pool, start, end)
            await asyncio.to_thread(
                build_document, rows, f"Boshliq xabarlari — {start:%m.%Y}", path, tz
            )
        except PermissionError:
            return (
                "\n⚠️ Fayl Word'da ochiq, shuning uchun yangilanmadi. "
                "Yoping: keyingi xabarda yoki /oy buyrug'ida yangilanadi."
            )
        except Exception:
            log.exception("Hujjat yig'ilmadi: %s", path)
            return "\n⚠️ Hujjat faylini yangilashda xato bo'ldi. Xabar bazada saqlangan."
        return ""

    async def _update_ack(self, row: asyncpg.Record, text: str) -> None:
        if not row["ack_message_id"]:
            return
        try:
            await self._bot.edit_message_text(
                text=text, chat_id=row["chat_id"], message_id=row["ack_message_id"]
            )
        except TelegramAPIError as error:
            log.warning("Tasdiq xabari yangilanmadi: %s", error)
