# HC-3.3: Debian-based python:3.12-slim. Alpine is forbidden (musl breaks
# Pango/libthai text shaping needed for Thai line breaking, HC-3.4).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint / Thai typesetting runtime (spec §12). Book fonts are NOT
# installed here — they come exclusively from the mounted Global/fonts/ (HC-3.5).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libthai0 \
        libthai-data \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Books/ and Global/ are bind-mounted at runtime (docker-compose.yml).
# The container idles; developers exec into it: docker compose exec app kb ...
CMD ["sleep", "infinity"]
