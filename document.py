import logging
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document
from docx.document import Document as DocumentType
from docx.image.exceptions import UnrecognizedImageError
from docx.shared import Cm

from config import DOCS_DIR

log = logging.getLogger(__name__)

KIND_LABELS = {
    "text": "Matn",
    "voice": "Ovozli xabar",
    "audio": "Audio",
    "video_note": "Dumaloq video",
    "video": "Video",
    "photo": "Rasm",
    "document": "Fayl",
    "other": "Boshqa",
}
AI_LABELS = {
    "voice": "Transkripsiya",
    "audio": "Transkripsiya",
    "video_note": "Transkripsiya",
    "video": "Transkripsiya",
    "photo": "Rasmdagi ma'lumot",
    "document": "Fayldagi ma'lumot",
}
MAX_IMAGE_WIDTH = Cm(14)
MAX_IMAGE_HEIGHT = Cm(18)

# Word XML'i ruxsat bermaydigan boshqaruv belgilari
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(text: str) -> str:
    return _CONTROL_CHARS.sub("", text)


def month_bounds(moment: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    local = moment.astimezone(tz)
    start = datetime(local.year, local.month, 1, tzinfo=tz)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def month_path(moment: datetime, tz: ZoneInfo) -> Path:
    return DOCS_DIR / f"Boshliq-xabarlari-{moment.astimezone(tz):%Y-%m}.docx"


def _add_image(doc: DocumentType, path: str) -> bool:
    try:
        shape = doc.add_picture(path, width=MAX_IMAGE_WIDTH)
    except (UnrecognizedImageError, OSError, ValueError) as error:
        log.warning("Rasm hujjatga qo'shilmadi: %s", error)
        return False
    if shape.height > MAX_IMAGE_HEIGHT:
        shape.width = int(shape.width * MAX_IMAGE_HEIGHT / shape.height)
        shape.height = MAX_IMAGE_HEIGHT
    return True


def _add_message(doc: DocumentType, row: Mapping, tz: ZoneInfo) -> None:
    kind = row["kind"]
    local = row["sent_at"].astimezone(tz)
    label = KIND_LABELS.get(kind, kind)
    doc.add_paragraph().add_run(
        _clean(f"{local:%H:%M} · {row['sender_name']} · {label}")
    ).bold = True

    if row["text_content"]:
        doc.add_paragraph(_clean(row["text_content"]))

    if row["file_path"] and (row["mime_type"] or "").startswith("image/"):
        if not _add_image(doc, row["file_path"]):
            doc.add_paragraph(f"Rasm fayli: {row['file_path']}").runs[0].italic = True
    elif row["file_path"]:
        name = row["file_name"] or Path(row["file_path"]).name
        doc.add_paragraph(_clean(f"Fayl: {name} ({row['file_path']})")).runs[0].italic = True

    if row["ai_text"]:
        heading = AI_LABELS.get(kind, "Ma'lumot")
        doc.add_paragraph().add_run(f"{heading}:").italic = True
        doc.add_paragraph(_clean(row["ai_text"]))

    if row["note"]:
        doc.add_paragraph(_clean(row["note"])).runs[0].italic = True
    if row["status"] == "pending":
        doc.add_paragraph("Hali qayta ishlanmoqda.").runs[0].italic = True
    elif row["status"] == "failed":
        doc.add_paragraph(
            "Matnini avtomatik o'qib bo'lmadi. Qayta urinish uchun botga /qayta yuboring."
        ).runs[0].italic = True


def build_document(rows: Iterable[Mapping], title: str, path: Path, tz: ZoneInfo) -> Path:
    rows = list(rows)
    doc = Document()
    doc.add_heading(title, 0)
    doc.add_paragraph(f"Jami xabarlar: {len(rows)}")

    current_day = None
    for row in rows:
        day = row["sent_at"].astimezone(tz).date()
        if day != current_day:
            doc.add_heading(f"{day:%d.%m.%Y}", 1)
            current_day = day
        _add_message(doc, row, tz)

    path.parent.mkdir(parents=True, exist_ok=True)
    # Yarim yozilgan hujjat qolmasligi uchun avval vaqtinchalik faylga saqlanadi
    temp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    try:
        doc.save(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path
