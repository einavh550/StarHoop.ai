FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# OpenCV and PyTorch runtime libraries for a slim Linux image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        python3-dev \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libpq-dev \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY src ./src
COPY tests ./tests
COPY alembic ./alembic
COPY alembic.ini ./
COPY pytest.ini ./
COPY README.md ./

RUN mkdir -p /app/uploads/videos /app/uploads/composed /app/uploads/compose_work

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]