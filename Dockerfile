# ---------- 1단계: 프론트엔드 빌드 ----------
# frontend/dist는 git에 없으므로 이미지 안에서 매번 빌드해 소스와 어긋나지 않게 한다.
FROM node:24-slim AS frontend

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------- 2단계: 백엔드 ----------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 리랭커(bge-reranker-v2-m3) 등 HF 모델 캐시. 볼륨으로 붙이면 재시작마다 다시 받지 않는다.
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

# 실행 중 쓰는 디렉터리 (storage/schema.sql은 이미지에 포함됨)
RUN mkdir -p storage data/uploads temp markdown

EXPOSE 8000

# FastAPI 앱은 프로젝트 루트의 main.py에 있다
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
