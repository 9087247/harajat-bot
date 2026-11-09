import asyncio
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    FSInputFile,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

import db
from config import Config
from document import build_document, month_bounds
from worker import Worker

log = logging.getLogger(__name__)

# Telegram botlarga shundan katta faylni yuklab olishga ruxsat bermaydi
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024

HELP_TEXT = (
    "Boshliqdan kelgan xabarlarni shu yerga yo'naltiring: matn, ovoz, rasm, video yoki fayl. "
    "Har biri avtomatik oylik Word hujjatga qo'shiladi.\n\n"
    "/bugun — bugungi hujjat\n"
    "/hafta — oxirgi 7 kun\n"
    "/oy — shu oy (/oy 2026-10 — tanlangan oy)\n"
    "/holat — navbat holati\n"
    "/qayta — o'qilmagan xabarlarni qayta urinish"
)


@dataclass
class Attachment:
    kind: str
    file_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


def extract_attachment(message: Message) -> Attachment:
    if message.voice:
        v = message.voice
        return Attachment("voice", v.file_id, None, v.mime_type or "audio/ogg", v.file_size)
    if message.audio:
        a = message.audio
        return Attachment("audio", a.file_id, a.file_name, a.mime_type or "audio/mpeg", a.file_size)
    if message.video_note:
        n = message.video_note
        return Attachment("video_note", n.file_id, None, "video/mp4", n.file_size)
    if message.video:
        v = message.video
        return Attachment("video", v.file_id, v.file_name, v.mime_type or "video/mp4", v.file_size)
    if message.photo:
        p = message.photo[-1]
        return Attachment("photo", p.file_id, None, "image/jpeg", p.file_size)
    if message.document:
        d = message.document
        return Attachment("document", d.file_id, d.file_name, d.mime_type, d.file_size)
    if message.text or message.caption:
        return Attachment("text")
    return Attachment("other")


def sender_name(message: Message) -> str:
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.full_name
    if isinstance(origin, MessageOriginHiddenUser):
        return origin.sender_user_name
    if isinstance(origin, MessageOriginChat):
        return origin.author_signature or origin.sender_chat.title or "Guruh"
    if isinstance(origin, MessageOriginChannel):
        return origin.author_signature or origin.chat.title or "Kanal"
    return message.from_user.full_name if message.from_user else "Noma'lum"


def setup_router() -> Router:
    """OWNER_TELEGRAM_ID hali yozilmaganda ishlaydi: faqat ID raqamni aytadi."""
    router = Router()

    @router.message()
    async def tell_id(message: Message) -> None:
        await message.answer(
            f"Sizning Telegram ID raqamingiz: {message.from_user.id}\n"
            "Uni .env faylidagi OWNER_TELEGRAM_ID ga yozing va botni qayta ishga tushiring."
        )

    return router


def owner_router(owner_id: int) -> Router:
    router = Router()
    # Begonalarning xabarlari javobsiz e'tiborsiz qoldiriladi
    router.message.filter(F.from_user.id == owner_id)

    @router.message(CommandStart())
    @router.message(Command("yordam"))
    async def start(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("bugun"))
    async def today(message: Message, pool: asyncpg.Pool, config: Config) -> None:
        now = datetime.now(config.timezone)
        start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        await _send_report(
            message, pool, config, start_at, start_at + timedelta(days=1),
            f"Boshliq xabarlari — {now:%d.%m.%Y}", f"Boshliq-xabarlari-{now:%Y-%m-%d}.docx",
        )

    @router.message(Command("hafta"))
    async def week(message: Message, pool: asyncpg.Pool, config: Config) -> None:
        now = datetime.now(config.timezone)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        start_at = tomorrow - timedelta(days=7)
        await _send_report(
            message, pool, config, start_at, tomorrow,
            f"Boshliq xabarlari — {start_at:%d.%m} – {now:%d.%m.%Y}",
            f"Boshliq-xabarlari-{start_at:%Y-%m-%d}_{now:%Y-%m-%d}.docx",
        )

    @router.message(Command("oy"))
    async def month(
        message: Message, command: CommandObject, pool: asyncpg.Pool, config: Config
    ) -> None:
        moment = datetime.now(config.timezone)
        if command.args:
            try:
                moment = datetime.strptime(command.args.strip(), "%Y-%m").replace(
                    tzinfo=config.timezone
                )
            except ValueError:
                await message.answer("Oyni shunday yozing: /oy 2026-10")
                return
        start_at, end_at = month_bounds(moment, config.timezone)
        await _send_report(
            message, pool, config, start_at, end_at,
            f"Boshliq xabarlari — {start_at:%m.%Y}", f"Boshliq-xabarlari-{start_at:%Y-%m}.docx",
        )

    @router.message(Command("holat"))
    async def status(message: Message, pool: asyncpg.Pool) -> None:
        counts = await db.status_counts(pool)
        await message.answer(
            f"Tayyor: {counts.get('done', 0)}\n"
            f"Navbatda: {counts.get('pending', 0)}\n"
            f"O'qilmagan: {counts.get('failed', 0)}"
        )

    @router.message(Command("qayta"))
    async def retry(message: Message, pool: asyncpg.Pool, worker: Worker) -> None:
        count = await db.retry_failed(pool)
        worker.wake()
        await message.answer(f"Qayta navbatga qo'yildi: {count} ta xabar.")

    @router.message()
    async def collect(message: Message, pool: asyncpg.Pool, worker: Worker) -> None:
        attachment = extract_attachment(message)
        note = None
        file_id = attachment.file_id
        if attachment.kind == "other":
            note = f"Bu xabar turi saqlanmadi: {message.content_type}."
        elif (attachment.file_size or 0) > TELEGRAM_DOWNLOAD_LIMIT:
            note = (
                "Fayl 20 MB dan katta: Telegram botga uni yuklab olishga ruxsat bermaydi. "
                "Asl xabarni Telegram'dan qarang."
            )
            file_id = None

        # Tasdiq avval yuboriladi: navbatdagi qatorda uning id'si doim bo'lishi kerak
        ack = await message.reply("⏳ Qabul qilindi, qayta ishlanmoqda…")

        origin = message.forward_origin
        message_id = await db.insert_message(
            pool,
            chat_id=message.chat.id,
            telegram_message_id=message.message_id,
            kind=attachment.kind,
            sender_name=sender_name(message),
            sent_at=origin.date if origin else message.date,
            text_content=message.text or message.caption,
            file_id=file_id,
            file_name=attachment.file_name,
            mime_type=attachment.mime_type,
            note=note,
            ack_message_id=ack.message_id,
        )
        if message_id is None:
            await ack.delete()
            return
        worker.wake()

    return router


async def _send_report(
    message: Message,
    pool: asyncpg.Pool,
    config: Config,
    start_at: datetime,
    end_at: datetime,
    title: str,
    file_name: str,
) -> None:
    rows = await db.messages_between(pool, start_at, end_at)
    if not rows:
        await message.answer("Bu davrda xabar yo'q.")
        return

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / file_name
        await asyncio.to_thread(build_document, rows, title, path, config.timezone)
        try:
            await message.answer_document(FSInputFile(path, filename=file_name))
        except TelegramAPIError as error:
            log.warning("Hujjat yuborilmadi: %s", error)
            await message.answer(
                "Hujjatni Telegram orqali yuborib bo'lmadi (ehtimol juda katta). "
                "Qisqaroq davrni tanlang: /bugun yoki /hafta."
            )
