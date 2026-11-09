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
    error_message text,                          -- 실패 원인
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
    created_at  TEXT NOT NULL DEFAULT current_timestamp,
    updated_at  TEXT NOT NULL DEFAULT current_timestamp
);

-- product: 우리 제품 (모델 단위. N5800, A650 ...)
CREATE TABLE IF NOT EXISTS product (
    id          TEXT PRIMARY KEY,                -- uuid
    model       TEXT NOT NULL UNIQUE,            -- 모델명
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
-- aliases.yaml에서 넣은 상위 개념(concept)과 그 연결은 file_id가 NULL이다.

-- graph_entity: 개체. 같은 type 안에서 norm(소문자, 공백·기호 제거)이 같으면 같은 개체로 본다.
create table if not exists graph_entity (
    id         integer primary key autoincrement,
    type       text not null,                  -- graph_rag/types.py ENTITY_TYPES
    name       text not null,                  -- 처음 뽑힌 표기 (화면 표시용)
    norm       text not null,                  -- 비교용 정규화 키
    created_at text not null default current_timestamp,
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
    -- extract: 문서에서 뽑음 (페이지를 다시 뽑으면 갈아끼운다) / seed: aliases.yaml / manual: 화면에서 사람이 넣음 (다시 뽑아도 유지)
    -- 기존 DB에는 repo_connect.py의 마이그레이션이 이 컬럼을 추가한다
    origin     text not null default 'extract' check (origin in ('extract', 'seed', 'manual')),
    created_at text not null default current_timestamp
);
-- file_id가 NULL인 행도 중복을 막도록 빈 문자열/-1로 바꿔 유일성을 건다
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_relation_unique
    ON graph_relation(src_id, dst_id, type, ifnull(file_id, ''), ifnull(page, -1));
CREATE INDEX IF NOT EXISTS idx_graph_relation_dst ON graph_relation(dst_id);
CREATE INDEX IF NOT EXISTS idx_graph_relation_file ON graph_relation(file_id, page);

-- graph_relation_block: 사람이 화면에서 지운 관계. 문서를 다시 뽑거나 서버가 aliases.yaml을 다시 넣어도 되살리지 않는다.
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
