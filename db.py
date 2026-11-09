from datetime import datetime

import asyncpg

MAX_ATTEMPTS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id                  BIGSERIAL PRIMARY KEY,
    chat_id             BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    kind                TEXT NOT NULL,
    sender_name         TEXT NOT NULL,
    sent_at             TIMESTAMPTZ NOT NULL,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    text_content        TEXT,
    file_id             TEXT,
    file_name           TEXT,
    mime_type           TEXT,
    file_path           TEXT,
    ai_text             TEXT,
    note                TEXT,
    ack_message_id      BIGINT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'done', 'failed')),
    attempts            INT NOT NULL DEFAULT 0,
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error          TEXT,
    UNIQUE (chat_id, telegram_message_id)
);
CREATE INDEX IF NOT EXISTS messages_sent_at_idx ON messages (sent_at);
CREATE INDEX IF NOT EXISTS messages_due_idx ON messages (next_attempt_at)
    WHERE status = 'pending';
"""


async def connect(database_url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    return pool


async def insert_message(
    pool: asyncpg.Pool,
    *,
    chat_id: int,
    telegram_message_id: int,
    kind: str,
    sender_name: str,
    sent_at: datetime,
    text_content: str | None,
    file_id: str | None,
    file_name: str | None,
    mime_type: str | None,
    note: str | None,
    ack_message_id: int,
) -> int | None:
    """Yangi qator id'sini qaytaradi; xabar avval saqlangan bo'lsa None."""
    return await pool.fetchval(
        """
        INSERT INTO messages (chat_id, telegram_message_id, kind, sender_name, sent_at,
                              text_content, file_id, file_name, mime_type, note, ack_message_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (chat_id, telegram_message_id) DO NOTHING
        RETURNING id
        """,
        chat_id, telegram_message_id, kind, sender_name, sent_at,
        text_content, file_id, file_name, mime_type, note, ack_message_id,
    )


async def due_messages(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT * FROM messages
        WHERE status = 'pending' AND next_attempt_at <= now()
        ORDER BY id
        LIMIT 20
        """
    )


async def set_file_path(pool: asyncpg.Pool, message_id: int, file_path: str) -> None:
    await pool.execute("UPDATE messages SET file_path = $2 WHERE id = $1", message_id, file_path)


async def mark_done(pool: asyncpg.Pool, message_id: int, ai_text: str | None) -> None:
    await pool.execute(
        """
        UPDATE messages
        SET status = 'done', ai_text = $2, last_error = NULL
        WHERE id = $1
        """,
        message_id, ai_text,
    )


async def mark_error(pool: asyncpg.Pool, message_id: int, error: str) -> bool:
    """Xatoni yozadi va orqaga surib qayta urinishni belgilaydi. Urinishlar tugasa True."""
    attempts = await pool.fetchval(
        """
        UPDATE messages
        SET attempts = attempts + 1,
            last_error = $2,
            status = CASE WHEN attempts + 1 >= $3 THEN 'failed' ELSE 'pending' END,
            next_attempt_at = now() + make_interval(mins => power(2, attempts + 1)::int)
        WHERE id = $1
        RETURNING attempts
        """,
        message_id, error[:500], MAX_ATTEMPTS,
    )
    return attempts >= MAX_ATTEMPTS


async def retry_failed(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        """
        UPDATE messages
        SET status = 'pending', attempts = 0, next_attempt_at = now()
        WHERE status = 'failed'
        """
    )
    return int(result.split()[-1])


async def messages_between(
    pool: asyncpg.Pool, start: datetime, end: datetime
) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM messages WHERE sent_at >= $1 AND sent_at < $2 ORDER BY sent_at, id",
        start, end,
    )


async def status_counts(pool: asyncpg.Pool) -> dict[str, int]:
    rows = await pool.fetch("SELECT status, count(*) AS n FROM messages GROUP BY status")
    return {row["status"]: row["n"] for row in rows}
