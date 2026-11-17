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
    type          TEXT NOT NULL,        -- 'image', 'pdf', 'docx', 'xlsx' 등
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    image_data    TEXT,                 -- 이미지: data URL(base64)
    stored_path   TEXT,                 -- 이미지 외 파일: 저장 경로
    created_at    TEXT NOT NULL DEFAULT current_timestamp,
    FOREIGN KEY (mail_uid) REFERENCES mails(uid) ON DELETE CASCADE,
    CHECK (
        (type =  'image' AND image_data  IS NOT NULL) OR
        (type <> 'image' AND stored_path IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_mail_attachments_mail_uid ON mail_attachments(mail_uid);

-- attachment_page: 메일 첨부 문서의 페이지별 텍스트. 에이전트가 read_attachment로 처음 읽을 때 한 번 파싱해 저장한다.
-- (등록 문서와 달리 첨부는 업로드 단계가 없어 질의 시점 파싱을 허용한다. 같은 첨부는 다시 파싱하지 않는다)
CREATE TABLE IF NOT EXISTS attachment_page (
    attachment_id  INTEGER NOT NULL REFERENCES mail_attachments(attachment_id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,          -- 파서가 돌려준 순서 (0부터)
    page           INTEGER NOT NULL,
    text           TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (attachment_id, seq)
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
    last_review_id INTEGER,            -- 초안에 이미 반영한 마지막 반려(task_reviews.review_id). 기존 DB는 마이그레이션이 추가
    validation_json TEXT,              -- 초안의 근거 검증 결과 {ok, errors, warnings, cited_ids} (기존 DB는 마이그레이션이 추가)
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
    cited       INTEGER NOT NULL DEFAULT 0,   -- 1: 답변이 '근거:' 줄로 인용한 근거, 0: 읽기만 한 근거 (기존 DB는 마이그레이션이 추가)
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_sources_task_id ON task_sources(task_id);


-- task_reviews: 담당자 검토 이력 (반려 사유·처리 시각). 한 task가 여러 번 반려될 수 있다.
CREATE TABLE IF NOT EXISTS task_reviews (
    review_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('reject', 'mark_sent', 'retry')),  -- mark_sent: 수락 여부를 모르던 발송을 담당자가 보낸 것으로 확인, retry: 생성 실패 작업 다시 생성
    reason      TEXT,
    requeue     INTEGER NOT NULL DEFAULT 1,   -- 반려 후 재작성 대기로 돌렸는지 (0/1)
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_reviews_task_id ON task_reviews(task_id);


-- task_send: 답변 발송 시도. 승인 시점의 본문·수신자·첨부를 고정하고 SMTP 결과를 남긴다.
-- outcome: NULL(발송 중) | sent | send_failed | send_unknown. 자동 재발송은 하지 않는다.
CREATE TABLE IF NOT EXISTS task_send (
    send_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT NOT NULL,
    body             TEXT NOT NULL,
    recipient        TEXT NOT NULL,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    attempted_at     TEXT NOT NULL,
    outcome          TEXT,
    detail           TEXT,
    cleanup_warning  TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_send_task_id ON task_send(task_id);


-- file_group: 사용자가 만드는 문서 묶음. 소속 파일과 검색 청크에 같은 group_id를 저장한다.
-- 기존 버전의 고정 그룹은 데이터가 있거나 사용자가 수정했다면 유지한다.
create table if not exists file_group (
    id          text primary key,              -- 신규 그룹은 UUID, 기존 그룹은 과거 키를 유지
    name        text not null,
    description text not null default '',      -- 그룹의 역할 (어떤 문서들이 모였는지)
    created_at  text not null default current_timestamp,
    updated_at  text not null default current_timestamp
);


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
    error_message text,                          -- 실패 원인 (검수 완료 뒤 색인 실패 포함)
    -- 문서 검수: 업로드는 파싱까지만 하고 'pending'으로 둔다. 파일 검수에서 [검수 완료]를 눌러야
    -- 청킹·임베딩·그래프 추출을 하고 'done'이 된다. 'pending' 문서는 검색·문서 도구·그래프에 쓰이지 않는다.
    -- 이 단계가 생기기 전에 올린 문서는 이미 색인돼 있어 'done'이다 (repo_connect._migrate).
    review_status text not null default 'done'
                  check (review_status in ('pending', 'done')),
    created_at    text not null default current_timestamp,
    updated_at    text not null default current_timestamp,
    -- 소속 그룹. 아직 분류 전이면 NULL, 그룹이 지워지면 NULL로 돌아간다.
    -- 기존 DB에는 repo_connect.py의 마이그레이션이 이 컬럼과 idx_file_group_id 인덱스를 추가한다.
    group_id      text references file_group(id) on delete set null,
    description   text not null default ''       -- 파일 내용을 짧게 설명 (기존 DB는 마이그레이션이 추가)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_sha256 ON file(sha256);


-- file_relation: 서로 연관된 파일 쌍 (파일 N : 파일 N). 방향이 없는 관계다.
-- 같은 쌍이 (A,B)와 (B,A)로 두 번 들어가지 않도록 file_id < related_file_id 순서로만 저장한다.
-- 둘 중 한 파일이 지워지면 관계도 같이 지워진다.
create table if not exists file_relation (
    file_id         text not null references file(file_id) on delete cascade,
    related_file_id text not null references file(file_id) on delete cascade,
    created_at      text not null default current_timestamp,
    primary key (file_id, related_file_id),
    check (file_id < related_file_id)
);
-- primary key가 file_id 쪽 조회를 맡고, 반대쪽 조회는 이 인덱스가 맡는다
CREATE INDEX IF NOT EXISTS idx_file_relation_related ON file_relation(related_file_id);


-- prompt: 답변 지침(시스템 프롬프트). 여러 개 저장하고 그중 하나만 선택해 쓴다.
-- 기본 프롬프트(is_default = 1)는 서버 시작 시 없으면 agent/prompt.py 내용으로 넣는다.
-- 선택된 프롬프트가 없으면 기본 프롬프트를, DB를 못 읽으면 agent/prompt.py 원문을 쓴다.
CREATE TABLE IF NOT EXISTS prompt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                 -- 목록에서 구분할 이름
    content     TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    is_selected INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- is_default = 1, is_selected = 1 인 행은 각각 DB 전체에 하나만 허용
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_default ON prompt(is_default) WHERE is_default = 1;
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_selected ON prompt(is_selected) WHERE is_selected = 1;


CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_mail_uid ON tasks(mail_uid);


-- ===== 제품·부품 사양 (입찰 조건 판정용 구조화 데이터) =====
-- 문서(세일즈 가이드 등)는 근거로만 쓰고, 판정에 쓰는 값은 여기에 사람이 검증해 넣는다.

-- spec_attribute: 속성 사전. 사양 값은 반드시 이 키로 저장한다. 비교 코드는 data_type과 unit을 본다.
-- 기본 속성(entity/spec.py DEFAULT_ATTRIBUTES)은 자동으로 넣지 않고 화면의 "기본 속성 추가"로 넣는다.
CREATE TABLE IF NOT EXISTS spec_attribute (
    key         TEXT PRIMARY KEY,                -- 예: cpu_cores, ram_max_gb (영문 소문자·숫자·_)
    name        TEXT NOT NULL,                   -- 화면 이름 (예: CPU 코어 수)
    category    TEXT NOT NULL DEFAULT 'other',   -- entity/spec.py ATTRIBUTE_CATEGORIES
    data_type   TEXT NOT NULL DEFAULT 'text' CHECK (data_type IN ('number', 'text', 'bool')),
    unit        TEXT NOT NULL DEFAULT '',        -- number일 때 단위 (GB, GHz, kg ...)
    description TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    -- 1이면 파생 모델에 자기 값이 없을 때 가장 가까운 상위 모델의 값을 물려받는다. 인증(cert) 속성은 1이 될 수 없다.
    -- 기존 DB에는 repo_connect.py의 마이그레이션이 추가한다
    inheritable INTEGER NOT NULL DEFAULT 0 CHECK (inheritable IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT current_timestamp,
    updated_at  TEXT NOT NULL DEFAULT current_timestamp
);

-- product: 우리 제품 (모델 단위. N5800, A650 ...)
-- parent_id가 있으면 그 제품의 하위 모델(파생 모델, 예: N5800 → N5800-GB70-PU02)이다. 단계는 여러 개 둘 수 있다.
-- 하위 모델이 있는 제품은 저장소가 지우지 못하게 막는다.
CREATE TABLE IF NOT EXISTS product (
    id          TEXT PRIMARY KEY,                -- uuid
    model       TEXT NOT NULL UNIQUE,            -- 모델명
    parent_id   TEXT REFERENCES product(id),     -- 상위 모델. NULL이면 최상위 모델
    name        TEXT NOT NULL DEFAULT '',        -- 표시 이름 (예: N5800 14세대)
    category    TEXT NOT NULL DEFAULT 'notebook', -- entity/spec.py PRODUCT_CATEGORIES
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'planned', 'eol')),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT current_timestamp,
    updated_at  TEXT NOT NULL DEFAULT current_timestamp
);

-- component: 부품 (CPU, GPU, SSD ...). 코어 수·클럭처럼 사내 문서에 없는 값은 부품 사양으로 넣는다.
CREATE TABLE IF NOT EXISTS component (
    id          TEXT PRIMARY KEY,                -- uuid
    kind        TEXT NOT NULL DEFAULT 'other',   -- entity/spec.py COMPONENT_KINDS
    model       TEXT NOT NULL,                   -- 예: AMD Ryzen AI 7 350
    vendor      TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT current_timestamp,
    updated_at  TEXT NOT NULL DEFAULT current_timestamp,
    UNIQUE (kind, model)
);

-- spec_value: 제품 또는 부품(owner_type)의 사양 값 한 건. 같은 속성에 값이 여러 개(옵션)면 행이 여러 개다.
-- owner_id는 product.id 또는 component.id. 두 테이블을 가리켜서 FK 대신 저장소가 삭제 시 함께 지운다.
CREATE TABLE IF NOT EXISTS spec_value (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type     TEXT NOT NULL CHECK (owner_type IN ('product', 'component')),
    owner_id       TEXT NOT NULL,
    attribute_key  TEXT NOT NULL REFERENCES spec_attribute(key),
    value_text     TEXT NOT NULL,                -- 입력한 값 그대로
    value_num      REAL,                         -- number면 파싱한 숫자, bool이면 1/0, text면 NULL
    is_option      INTEGER NOT NULL DEFAULT 0 CHECK (is_option IN (0, 1)),  -- 선택 구성 여부
    note           TEXT NOT NULL DEFAULT '',
    source_file_id TEXT,                         -- 근거 문서 file.file_id (문서가 지워져도 남긴다)
    source_page    INTEGER,
    source_note    TEXT NOT NULL DEFAULT '',     -- 예: "R&D 홍길동 2026-11-05"
    created_at     TEXT NOT NULL DEFAULT current_timestamp,
    updated_at     TEXT NOT NULL DEFAULT current_timestamp,
    UNIQUE (owner_type, owner_id, attribute_key, value_text)
);
CREATE INDEX IF NOT EXISTS idx_spec_value_owner ON spec_value(owner_type, owner_id);

-- product_component: 제품에 들어가는 부품. is_option = 1 이면 선택 구성.
CREATE TABLE IF NOT EXISTS product_component (
    product_id   TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    component_id TEXT NOT NULL REFERENCES component(id) ON DELETE CASCADE,
    is_option    INTEGER NOT NULL DEFAULT 0 CHECK (is_option IN (0, 1)),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (product_id, component_id)
);
CREATE INDEX IF NOT EXISTS idx_product_component_component ON product_component(component_id);


-- file_page: 업로드 때 파서가 뽑은 페이지별 텍스트 (파일 1 : 페이지 N).
-- 파일 검수는 text만 고치고, 그 페이지를 다시 청킹·임베딩한다. original_text(파싱 원문)와 업로드 원본 파일은 건드리지 않는다.
-- xlsx는 한 시트(page)가 여러 블록으로 나뉘어 오므로 page가 같은 행이 여럿일 수 있다. 순서는 seq로 지킨다.
create table if not exists file_page (
    page_id       integer primary key autoincrement,
    file_id       text not null references file(file_id) on delete cascade,
    seq           integer not null,               -- 파서가 돌려준 순서 (0부터)
    page          integer not null,               -- 1부터 시작하는 페이지(시트) 번호. 청크 메타데이터의 page와 같다
    text          text not null,                  -- 검색에 쓰는 현재 텍스트 (검수로 수정)
    original_text text not null,                  -- 업로드 때 파싱 결과. 수정하지 않는다
    created_at    text not null default current_timestamp,
    updated_at    text not null default current_timestamp,
    unique (file_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_file_page_file_page ON file_page(file_id, page);


-- ===== 문서 그래프 (Graph RAG) =====
-- 업로드 문서의 페이지 텍스트(file_page.text)에서 LLM으로 뽑은 개체와 관계. 사양 DB와는 별개다.
-- 문서에서 뽑은 행은 file_id에 걸려 있어 파일이 지워지면 같이 지워진다. 남는 개체는 graph_repository.prune_orphans()가 치운다.
-- 사양 DB에서 심은 것(spec)과 근거 없이 사람이 넣은 것(manual)은 file_id가 NULL이다. 시스템 상위 개념(concept)은 없다 (GR1).

-- graph_entity: 개체. 같은 type 안에서 norm(소문자, 공백·기호 제거)이 같으면 같은 개체로 본다.
create table if not exists graph_entity (
    id         integer primary key autoincrement,
    type       text not null,                  -- graph_rag/types.py ENTITY_TYPES
    name       text not null,                  -- 처음 뽑힌 표기 (화면 표시용)
    norm       text not null,                  -- 비교용 정규화 키
    created_at text not null default current_timestamp,
    -- 사양 DB의 같은 대상 (ref_type: 'product' | 'component', ref_id: product.id 또는 component.id). 없으면 NULL.
    -- graph_search가 돌려주고 모델이 get_specs에 그대로 넘긴다. 기존 DB에는 repo_connect.py의 마이그레이션이 추가한다
    ref_type   text,
    ref_id     text,
    unique (type, norm)
);
CREATE INDEX IF NOT EXISTS idx_graph_entity_norm ON graph_entity(norm);

-- graph_alias: 개체의 다른 표기. 검색어를 개체로 바꿀 때 쓴다.
create table if not exists graph_alias (
    entity_id  integer not null references graph_entity(id) on delete cascade,
    alias      text not null,
    alias_norm text not null,
    primary key (entity_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_graph_alias_norm ON graph_alias(alias_norm);

-- graph_mention: 개체가 나온 문서 페이지. 그래프 검색 결과를 원본 문서로 잇는다.
create table if not exists graph_mention (
    entity_id integer not null references graph_entity(id) on delete cascade,
    file_id   text not null references file(file_id) on delete cascade,
    page      integer not null,
    primary key (entity_id, file_id, page)
);
CREATE INDEX IF NOT EXISTS idx_graph_mention_file ON graph_mention(file_id, page);

-- graph_relation: 개체 사이의 방향 있는 관계. file_id/page는 그 관계를 뽑은 근거 페이지다.
create table if not exists graph_relation (
    id         integer primary key autoincrement,
    src_id     integer not null references graph_entity(id) on delete cascade,
    dst_id     integer not null references graph_entity(id) on delete cascade,
    type       text not null,                  -- graph_rag/types.py RELATION_TYPES
    file_id    text references file(file_id) on delete cascade,  -- 근거 문서. seed와 근거 없이 넣은 manual은 NULL
    page       integer,
    -- extract: 문서에서 뽑음 (페이지를 다시 뽑으면 갈아끼운다) / seed: 옛 aliases.yaml (GR1에서 없앰) / manual: 화면에서 사람이 넣음 (다시 뽑아도 유지)
    -- spec: 사양 DB에서 심음 (제품 상위·파생 모델, 제품-부품 연결. 서버 시작·사양 변경 때 spec 관계만 다시 넣는다)
    -- 기존 DB에는 repo_connect.py의 마이그레이션이 이 컬럼을 추가하고, CHECK에 spec이 없으면 테이블을 새로 만들어 옮긴다
    origin     text not null default 'extract' check (origin in ('extract', 'seed', 'manual', 'spec')),
    -- spec 관계의 옵션 여부 (product_component.is_option). 다른 출처는 0
    is_option  integer not null default 0 check (is_option in (0, 1)),
    created_at text not null default current_timestamp
);
-- file_id가 NULL인 행도 중복을 막도록 빈 문자열/-1로 바꿔 유일성을 건다
-- Source-aware uniqueness and editing tables are installed transactionally by graph_migration.py.
CREATE INDEX IF NOT EXISTS idx_graph_relation_dst ON graph_relation(dst_id);
CREATE INDEX IF NOT EXISTS idx_graph_relation_file ON graph_relation(file_id, page);

-- graph_relation_block: 사람이 화면에서 지운 관계. 문서를 다시 뽑거나 서버가 사양 DB를 다시 심어도 되살리지 않는다.
-- 개체 id는 다시 뽑으면 바뀔 수 있으므로 (종류, 정규화 이름)으로 기억한다. 같은 관계를 화면에서 다시 넣으면 지운다.
create table if not exists graph_relation_block (
    src_type   text not null,
    src_norm   text not null,
    type       text not null,
    dst_type   text not null,
    dst_norm   text not null,
    created_at text not null default current_timestamp,
    primary key (src_type, src_norm, type, dst_type, dst_norm)
);

-- access_log: HTTP 접속 기록. app/access_log.py 미들웨어가 모아서 넣고, ACCESS_LOG_RETENTION_DAYS가 지나면 지운다.
-- 정적 파일(/assets/)과 상태 대시보드 폴링(/monitor/)은 남기지 않는다.
create table if not exists access_log (
    id          integer primary key autoincrement,
    ts          text not null,                  -- UTC '2026-11-10T03:15:42Z'
    client_ip   text not null default '',
    method      text not null,
    path        text not null,                  -- 실제 요청 경로
    route       text not null,                  -- 묶음 기준: API는 경로 템플릿(/file/{file_id}), 화면은 실제 경로
    query       text not null default '',
    status      integer not null,
    duration_ms real not null,
    user_agent  text not null default ''
);
CREATE INDEX IF NOT EXISTS idx_access_log_ts ON access_log(ts);
CREATE INDEX IF NOT EXISTS idx_access_log_ip ON access_log(client_ip);

-- qa_log: 질의응답 화면(/ask, /ask/attachments)의 질문 한 건과 그 결과. 화면의 좋음/아쉬움 평가가 나중에 붙는다.
-- 실행 기록(run)은 웹 질문이면 SESSION_EVIDENCE_RETENTION_DAYS가 지나면 지워지므로, 비교에 필요한 값
-- (모델, 도구 호출, 토큰)은 여기에 복사해 둔다. 이 표는 자동으로 지우지 않는다.
CREATE TABLE IF NOT EXISTS qa_log (
    log_id           TEXT PRIMARY KEY,          -- 'q' + 짧은 uuid
    asked_at         TEXT NOT NULL,             -- 서버 지역 시각 ISO
    client_ip        TEXT NOT NULL DEFAULT '',
    endpoint         TEXT NOT NULL,             -- 'ask' | 'ask_attachments'
    mode             TEXT NOT NULL,             -- 'claude' | 'local'
    question         TEXT NOT NULL,
    attachments_json TEXT,                      -- [{"filename", "type"}] (첨부 질문만)
    status           TEXT NOT NULL,             -- 'ok' | 'error'
    answer           TEXT,
    error            TEXT,
    sources_json     TEXT,                      -- 화면에 보낸 출처 그대로
    validation_json  TEXT,                      -- 답변 근거 검증 결과
    run_id           TEXT,
    model            TEXT,
    prompt_id        INTEGER,
    tools_available  TEXT,                      -- 그때 에이전트에 있던 도구 이름 (JSON 목록)
    tool_calls_json  TEXT,                      -- run.tool_calls_json 복사
    tokens_in        INTEGER,
    tokens_out       INTEGER,
    duration_ms      REAL NOT NULL,
    rating           TEXT,                      -- 'good' | 'bad' | NULL(평가 안 함)
    comment          TEXT,
    rated_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_qa_log_asked ON qa_log(asked_at);
CREATE INDEX IF NOT EXISTS idx_qa_log_rating ON qa_log(rating);


-- ===== 근거(evidence)와 에이전트 실행 기록 =====
-- evidence: 에이전트가 읽은 근거 한 조각. 답변은 evidence_id로 인용하고, 서버가 소유자(task/session)를 검증한다.
-- 같은 (소유자, 원천, 파일, 페이지 행, revision, 본문 해시)면 새 행을 만들지 않고 기존 ID를 돌려준다.
-- 그래프 검색 결과는 근거가 아니다 (실행 기록에만 남긴다).
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id   TEXT PRIMARY KEY,          -- 'e' + 짧은 uuid
    owner_type    TEXT NOT NULL,             -- 'task' | 'session'
    owner_id      TEXT NOT NULL,
    origin_type   TEXT NOT NULL,             -- 'file_page' | 'chunk' | 'attachment' | 'spec_value'
    file_id       TEXT, page_id INTEGER, page INTEGER,
    attachment_id INTEGER, spec_value_id INTEGER,
    revision      TEXT,                      -- file_page.updated_at 또는 첨부 파서 버전
    content_hash  TEXT NOT NULL,
    text          TEXT NOT NULL,
    source_name   TEXT,                      -- 화면 표시용 파일명 (임시 첨부처럼 file·mail_attachments에 없는 것도 이름을 보이게)
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_owner ON evidence(owner_type, owner_id);

-- run: 에이전트 실행 1회 (모델 호출부터 최종 답변까지)
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
    model TEXT, prompt_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT,
    status TEXT NOT NULL,                    -- 'running' | 'ok' | 'error' | 'limit'
    tool_calls_json TEXT, tokens_in INTEGER, tokens_out INTEGER, error TEXT,
    label TEXT,                              -- 실행 종류 ('메일(첨부 0건, 반려 없음)', '메일 반려 반영(…)' 등). 기존 DB는 마이그레이션이 추가
    answer TEXT,                             -- 그 실행이 만든 답변 본문(근거 줄 제외). 메일(task)의 ok 실행만 저장. 기존 DB는 마이그레이션이 추가
    skills_json TEXT                         -- 서버가 그 실행에 적용한 업무 절차 [{"name", "digest"}]. 기존 DB는 마이그레이션이 추가
);
CREATE INDEX IF NOT EXISTS idx_run_owner ON run(owner_type, owner_id);

-- evidence_use: 실행 중 근거를 어떻게 썼는지 (읽음 / 리랭크 / 답변 인용)
CREATE TABLE IF NOT EXISTS evidence_use (
    run_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
    action TEXT NOT NULL,                    -- 'read' | 'rerank' | 'cite'
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_use_run ON evidence_use(run_id, action);


-- ===== 문의 분석과 생성 절차 (지시서 I) =====
-- request_type: 문의 유형. 기본 유형(seed, 서버 시작 때 없을 때만 넣는다)과 분석이 만든 유형(model)
CREATE TABLE IF NOT EXISTS request_type (
    type_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,                  -- 짧은 이름 (30자 이하, 한 줄)
    description TEXT NOT NULL,                  -- 어떤 문의인지 (200자 이하, 한 줄)
    skill_name  TEXT,                           -- 이 유형을 맡는 절차. 없으면 NULL
    state       TEXT NOT NULL DEFAULT 'open',   -- open | no_skill_needed | merged
    merged_into INTEGER,                        -- state가 merged면 옮겨 간 유형
    origin      TEXT NOT NULL,                  -- seed | model
    created_at  TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- request_analysis: 문의(task) 1건의 분석 결과 (task 1 : 1. 다시 분석하면 덮어쓴다)
CREATE TABLE IF NOT EXISTS request_analysis (
    task_id          TEXT PRIMARY KEY,
    status           TEXT NOT NULL,             -- ok | error
    type_id          INTEGER,
    covered_by       TEXT,                      -- 분석이 고른 절차 이름. 없으면 NULL
    used_skills_json TEXT,                      -- 실제 실행이 쓴 절차 (서버 적용 + load_skill)
    reason           TEXT,
    model            TEXT, attempts INTEGER NOT NULL DEFAULT 1,
    error            TEXT, analyzed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_analysis_type ON request_analysis(type_id);

-- skill_doc: DB가 관리하는 절차. 버전마다 한 행이고 승인된 행은 바꾸지 않는다.
-- 사용 중인 절차 = 이름마다 approved·retired 행 중 가장 큰 version이 approved인 것.
-- 생성 중(generating) 행은 이름이 정해지기 전이라 '_generating-…' 임시 이름과 version 0을 쓴다.
CREATE TABLE IF NOT EXISTS skill_doc (
    doc_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    version           INTEGER NOT NULL,
    status            TEXT NOT NULL,            -- generating | draft | approved | rejected | retired | error
    description       TEXT, body TEXT, digest TEXT,
    type_id           INTEGER,
    source_tasks_json TEXT,                     -- 초안의 재료가 된 task_id 목록
    origin            TEXT NOT NULL,            -- generated | edited
    check_json        TEXT,                     -- 서버 검사 결과 {ok, errors, warnings}
    model             TEXT, error TEXT,
    created_at        TEXT NOT NULL,
    reviewed_at       TEXT, reviewed_by TEXT, review_note TEXT,
    UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS idx_skill_doc_type ON skill_doc(type_id, status);
CREATE INDEX IF NOT EXISTS idx_skill_doc_status ON skill_doc(status);


-- ===== 고객 이력과 담당자 메모 (통합 지시서 G1) =====
-- 고객 이력은 기존 기록(mails·tasks·request_analysis)에서 그때그때 조회한다. 사람이 남기는 메모만 여기에 둔다.
-- sender는 고객방과 같은 키 LOWER(TRIM(mails.sender)). 사용 중지한 메모(retired_at)는 이력 도구에 나오지 않는다.
CREATE TABLE IF NOT EXISTS customer_note (
    note_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    sender     TEXT NOT NULL,
    text       TEXT NOT NULL,                  -- 500자까지
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',       -- 요청 IP (로그인이 없다)
    retired_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_customer_note_sender ON customer_note(sender, retired_at);
