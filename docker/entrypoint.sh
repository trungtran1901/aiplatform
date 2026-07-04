#!/bin/sh
set -e

echo "[entrypoint] Waiting for database to accept connections..."
python - <<'PYEOF'
import asyncio
import sys
import time

import asyncpg
import os
import re

url = os.environ.get("DATABASE_URL", "")
# asyncpg.connect needs a plain postgres URL, strip the SQLAlchemy driver suffix
url = re.sub(r"\+asyncpg", "", url)

async def wait():
    for attempt in range(30):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            print("[entrypoint] Database is ready.")
            return
        except Exception as exc:
            print(f"[entrypoint] DB not ready yet ({exc}); retrying ({attempt+1}/30)...")
            time.sleep(2)
    print("[entrypoint] Database did not become ready in time.", file=sys.stderr)
    sys.exit(1)

asyncio.run(wait())
PYEOF

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Starting application..."
exec "$@"
