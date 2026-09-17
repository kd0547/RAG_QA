-- mails: 수신된 메일 원본 (불변에 가까운 사실 데이터)
CREATE TABLE IF NOT EXISTS mails (
    uid TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT DEFAULT '',
    received_at TEXT NOT NULL,
    attachments TEXT DEFAULT '',      -- 쉼표 구분 문자열
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_mail_uid ON tasks(mail_uid);