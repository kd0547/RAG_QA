#!/usr/bin/env bash
# 서버에서 git 브랜치를 받아 Docker로 다시 띄운다. (서버의 프로젝트 폴더가 git clone 상태일 때)
#
#   bash scripts/server_update.sh                 # 지금 브랜치를 최신으로
#   bash scripts/server_update.sh feat/graph-rag  # 다른 브랜치로 바꿔서
#
# 하는 일
#   1) storage/mail.db 백업 (storage/backup/mail.db.<시각>) — 새 버전이 시작할 때 테이블·컬럼을 추가하므로
#   2) git fetch → checkout → pull (서버에서 코드를 고친 게 있으면 멈춘다)
#   3) docker compose up -d --build
#   4) 앱이 응답할 때까지 기다린 뒤 문서 그래프 상태(/graph/stats)를 보여준다
#
# .env, storage/, data/, logs/ 는 건드리지 않는다.
set -euo pipefail

BRANCH="${1:-}"
PORT="${APP_PORT:-9092}"   # docker-compose.yml 의 "9092:8000"
BASE="http://localhost:${PORT}"

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "!! .env 가 없습니다. .env.example 을 복사해 채운 뒤 다시 실행하세요." >&2
    exit 1
fi

# ---------- 1. DB 백업 ----------
if [ -f storage/mail.db ]; then
    mkdir -p storage/backup
    backup="storage/backup/mail.db.$(date +%Y%m%d-%H%M%S)"
    # 앱이 쓰는 중이어도 일관된 사본을 만들려면 sqlite3 .backup 이 낫다. 없으면 파일 복사.
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 storage/mail.db ".backup '${backup}'"
    else
        cp storage/mail.db "${backup}"
    fi
    echo "DB 백업: ${backup}"
fi

# ---------- 2. 코드 받기 ----------
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "!! 서버에서 고친 코드가 있습니다. 확인 후 다시 실행하세요:" >&2
    git status --short --untracked-files=no >&2
    exit 1
fi
git fetch origin
if [ -n "${BRANCH}" ]; then
    git checkout "${BRANCH}" 2>/dev/null || git checkout -b "${BRANCH}" --track "origin/${BRANCH}"
fi
git pull --ff-only
echo "코드: $(git rev-parse --abbrev-ref HEAD) @ $(git log -1 --format='%h %s')"

# ---------- 3. 빌드·재시작 ----------
docker compose up -d --build

# ---------- 4. 확인 ----------
echo -n "앱 시작 대기"
for _ in $(seq 1 90); do
    if curl -fs "${BASE}/config" >/dev/null 2>&1; then
        echo " → 응답 확인 (${BASE})"
        echo "문서 그래프 상태:"
        curl -fs "${BASE}/graph/stats"
        echo
        echo "화면: ${BASE}/knowledge"
        exit 0
    fi
    echo -n "."
    sleep 2
done
echo
echo "!! 3분 안에 응답이 없습니다. 로그를 확인하세요: docker compose logs --tail 100 ragqa" >&2
exit 1
