-- mails: 수신된 메일 원본 (불변에 가까운 사실 데이터)
CREATE TABLE IF NOT EXISTS mails (
    uid TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT DEFAULT '',
    received_at TEXT NOT NULL,
    attachments TEXT DEFAULT '',      -- (미사용) 첨부파일은 mail_attachments 테이블 사용
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- mail_attachments: 메일 첨부파일 (메일 1 : 첨부 N)
CREATE TABLE IF NOT EXISTS mail_attachments (
    attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_uid      TEXT NOT NULL,
    type          TEXT NOT NULL CHECK (type IN ('pdf', 'image')),
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    image_data    TEXT,                 -- 이미지: data URL(base64)
    stored_path   TEXT,                 -- PDF: 저장 경로
    created_at    TEXT NOT NULL DEFAULT current_timestamp,
    FOREIGN KEY (mail_uid) REFERENCES mails(uid) ON DELETE CASCADE,
    CHECK (
        (type = 'image' AND image_data  IS NOT NULL) OR
        (type = 'pdf'   AND stored_path IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_mail_attachments_mail_uid ON mail_attachments(mail_uid);


-- tasks: mail 하나당 처리 워크플로우 상태
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    mail_uid TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    assignee TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    draft_answer TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (mail_uid) REFERENCES mails(uid)
);

-- task_sources: 답변 생성 시 에이전트가 참조한 문서 청크 (task 1 : 출처 N)
CREATE TABLE IF NOT EXISTS task_sources (
    source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    chunk_id    TEXT,                   -- 벡터DB 청크 ID
    file_id     TEXT,                   -- file.file_id (문서가 삭제될 수 있어 FK는 걸지 않음)
    source      TEXT NOT NULL,          -- 문서명
    page        INTEGER,
    chunk_index INTEGER,
    text        TEXT NOT NULL,          -- 근거 스니펫
    score       REAL,                   -- 유사도 점수
    created_at  TEXT NOT NULL DEFAULT current_timestamp,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_sources_task_id ON task_sources(task_id);


-- task_reviews: 담당자 검토 이력 (반려 사유·처리 시각). 한 task가 여러 번 반려될 수 있다.
CREATE TABLE IF NOT EXISTS task_reviews (
    review_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('reject')),
    reason      TEXT,
    requeue     INTEGER NOT NULL DEFAULT 1,   -- 반려 후 재작성 대기로 돌렸는지 (0/1)
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_reviews_task_id ON task_reviews(task_id);


create table if not exists file (
    file_id       text primary key,              -- uuid, Chroma 메타데이터의 file_id와 같은 값
    original_name text not null,                 -- 사용자가 올린 파일명 (화면 표시, 검색 결과 출처용)
    stored_path   text not null,                 -- 실제로 저장된 경로
    mime_type     text,
    size_bytes    integer,
    sha256        text,                          -- 같은 파일 중복 업로드 확인용
    status        text not null default 'processing'
                  check (status in ('processing', 'ready', 'failed', 'deleting')),
    chunk_count   integer,                       -- 인덱싱이 끝나면 채움
    error_message text,                          -- 실패 원인
    created_at    text not null default current_timestamp,
    updated_at    text not null default current_timestamp
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_sha256 ON file(sha256);


CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_mail_uid ON tasks(mail_uid);