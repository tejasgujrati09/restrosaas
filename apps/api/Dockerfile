FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
# WeasyPrint (QR sheet and menu PDFs) needs Pango; DejaVu supplies the rupee glyph.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
# Keep the virtualenv outside /app so the dev bind mount cannot shadow it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_NO_DEV=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
