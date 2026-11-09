"""Bot uchun PostgreSQL foydalanuvchisi va bazasini yaratadi. Qayta ishga tushirish xavfsiz."""
import asyncio
import os
from urllib.parse import urlparse

import asyncpg
from dotenv import load_dotenv

from config import BASE_DIR


async def main() -> None:
    load_dotenv(BASE_DIR / ".env", override=True)
    url = urlparse(os.environ["DATABASE_URL"])
    user, password, database = url.username, url.password, url.path.lstrip("/")

    conn = await asyncpg.connect(
        host=url.hostname,
        port=url.port,
        user="postgres",
        password=os.environ["POSTGRES_SUPERUSER_PASSWORD"],
        database="postgres",
    )
    try:
        quoted_user = await conn.fetchval("SELECT quote_ident($1)", user)
        quoted_db = await conn.fetchval("SELECT quote_ident($1)", database)
        quoted_password = await conn.fetchval("SELECT quote_literal($1)", password)

        action = (
            "ALTER"
            if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", user)
            else "CREATE"
        )
        await conn.execute(f"{action} ROLE {quoted_user} LOGIN PASSWORD {quoted_password}")

        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database):
            await conn.execute(f"CREATE DATABASE {quoted_db} OWNER {quoted_user} ENCODING 'UTF8' TEMPLATE template0")
    finally:
        await conn.close()
    print(f"Tayyor: {database} bazasi va {user} foydalanuvchisi")


if __name__ == "__main__":
    asyncio.run(main())
