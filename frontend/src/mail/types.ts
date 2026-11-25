/**
 * 메일 전송 승인 대시보드 - API 데이터 타입.
 * 백엔드 명세: docs/mail_approval_api.md
 */

export type MailStatus =
    | 'pending'      // 메일 수신, AI 초안 생성 대기
    | 'processing'   // AI 초안 생성 중 (서버 재시작 시 pending으로 돌아감)
    | 'drafted'      // 초안 생성 완료, 검토 대기
    | 'in_review'    // 담당자 검토 중
    | 'rejected'     // 반려 → 재작성 대기
    | 'approved'     // 승인, 전송 대기
    | 'sending'      // 승인 후 발송 중
    | 'sent'         // 전송 완료
    | 'send_failed'  // 메일 서버가 받지 않음 → 담당자가 다시 승인하면 재발송
    | 'send_unknown' // 발송 중 끊겨 전달 여부 모름 → 담당자가 '발송 확인됨' 또는 '재발송' 선택
    | 'failed';      // AI 초안 생성 실패

/** 목록(GET /mails)의 행 */
export interface MailSummary {
    task_id: string;
    subject: string;
    sender: string;                 // 이메일 주소
    received_at: string;            // ISO 8601 (+09:00)
    status: MailStatus;
}

export interface MailSource {
    source: string;                 // 문서 파일명
    page: number | null;
    text: string;                   // 근거 스니펫
    evidence_id?: string | null;    // 근거 ID (e…). 이전 버전 서버·예전 메일은 없음
    cited?: boolean;                // true: 답변이 인용한 근거, false: 읽기만 한 근거
}

/** 답장에 첨부할 수 있는 참고 문서 원본 (같은 파일은 한 번만) */
export interface MailAttachment {
    file_id: string;
    filename: string;
    mime_type: string | null;
    size_bytes: number | null;      // 파일이 없으면 null
    available: boolean;             // 서버 디스크에 파일이 있는지
    average_score?: number | null;  // 검색된 청크의 평균 유사도. 점수가 없으면 null
}

/** 초안의 근거 검증 결과 (서버가 답변 마지막 줄 '근거: …'를 검사) */
export interface DraftValidation {
    ok: boolean;
    errors: string[];               // 다른 질문의 근거 인용, 근거를 읽지 않고 답변 등
    warnings: string[];             // 근거 줄 없음, 읽지 않은 근거 인용 등
    cited_ids: string[];
}

/** 에이전트가 부른 도구 하나 (가장 최근 실행) */
export interface MailTraceItem {
    tool: string;
    args_summary: string;           // 인자 JSON 앞 200자
    at: string;                     // ISO 8601
}

/** 에이전트 실행 1회 (1차 초안, 반려 반영 …) */
export interface MailRun {
    run_id: string;
    label: string | null;           // 예: '메일(첨부 0건, 반려 없음)', '메일 반려 반영(review_id=1, 같은 대화)'. 예전 실행은 null
    status: 'running' | 'ok' | 'error' | 'limit';
    started_at: string;
    seconds: number | null;
    tokens_in: number | null;
    tokens_out: number | null;
    tool_calls: MailTraceItem[];
    skills?: AppliedSkill[];        // 서버가 이 실행에 붙인 SKILL (이전 버전 서버는 없음)
}

/** 상세(GET /mails/{task_id}) */
export interface MailDetail extends MailSummary {
    assignee: string | null;        // 검토 담당자
    recipient: string;
    body: string;                   // 받은 원문 (plain text)
    draft: string | null;           // AI 초안 (편집 대상)
    model: string | null;
    retrieval: { query_top_k: number | null; rerank_top_n: number | null } | null;
    sources: MailSource[];
    validation?: DraftValidation | null; // 검증 전에 만든 초안·이전 버전 서버는 없음
    read_sources?: MailSource[];    // 에이전트가 읽었지만 sources에 없는 근거 (인용하지 않음)
    trace?: MailTraceItem[];        // 가장 최근 실행의 도구 호출 (호환용)
    runs?: MailRun[];               // 이 메일의 실행 전체, 시작 순서 (이전 버전 서버는 없음)
    attachments?: MailAttachment[]; // 첨부 후보. 승인할 때 고른 것만 전송된다 (이전 버전 서버는 보내지 않음)
    created_at: string;
    updated_at: string;
}

export interface DailyVolume {
    date: string;                   // YYYY-MM-DD
    sent: number;
}

/** 대시보드 요약(GET /mails/stats) */
export interface MailStats {
    date: string;                   // YYYY-MM-DD
    pending_review: number;         // drafted + in_review
    sent_today: number;
    rejected_today: number;
    failed: number;
    avg_review_seconds: number | null;
    draft_adoption_rate: number | null;  // 무수정 승인 비율 0~1
    sent_delta: number | null;           // 전일 대비 오늘 전송 증감
    daily_volume: DailyVolume[];         // 최근 14일 (오래된 -> 최신)
}

export interface MailListResponse {
    items: MailSummary[];
    total: number;
    limit: number;
    offset: number;
}

export interface ApproveResult {
    task_id: string;
    status: MailStatus;
    sent_at: string;
    to: string;
}

// ---------- 고객방 (GET /customers, /customers/{sender}/timeline) — 조회 전용 ----------

/** 고객(발신자) 목록 한 줄. sender는 소문자·공백 제거 주소 */
export interface Customer {
    sender: string;
    mail_count: number;
    first_received_at: string;
    last_received_at: string;
    last_subject: string;
    last_task_id: string | null;
    status_counts: Partial<Record<MailStatus, number>>;
    needs_review: number;           // 검토 필요 상태(REVIEW_STATUSES) 건수
}

export interface CustomerListResponse {
    items: Customer[];
    total: number;
    limit: number;
    offset: number;
}

export interface AppliedSkill {
    name: string;
    digest: string;
}

/** inferred=true: 기록 이전 작업이라 서버가 추정한 사건 (시각·본문이 정확하지 않을 수 있음) */
export type TimelineEvent =
    | { type: 'received'; at: string; body: string; truncated: boolean; attachments: { filename: string; type: string }[] }
    | {
          type: 'draft'; at: string | null; run_id: string | null; label: string | null; answer: string | null;
          truncated: boolean; text_source: 'run' | 'task' | null; current: boolean; inferred: boolean; skills: AppliedSkill[];
      }
    | { type: 'run_failed'; at: string | null; run_id: string; label: string | null; status: 'error' | 'limit'; error: string | null }
    | { type: 'reject'; at: string; review_id: number; reason: string | null; truncated: boolean; requeue: boolean }
    | { type: 'retry'; at: string; review_id: number }
    | { type: 'mark_sent'; at: string; review_id: number; reason: string | null; truncated: boolean }
    | {
          type: 'send'; at: string | null; outcome: 'sent' | 'send_failed' | 'send_unknown' | 'sending';
          recipient: string | null; body: string | null; truncated: boolean; attachments: string[];
          detail: string | null; inferred: boolean;
      };

/** 문의(task) 한 건의 묶음. events는 received가 처음, 나머지는 시간순 */
export interface TimelineInquiry {
    task_id: string | null;
    subject: string;
    status: MailStatus | null;
    received_at: string;
    events: TimelineEvent[];
}

/** 담당자 메모 (GET /customers/{sender}/notes). 사용 중지(retired_at)한 메모는 답변 에이전트에 보이지 않는다 */
export interface CustomerNote {
    note_id: number;
    sender: string;
    text: string;
    created_at: string;
    created_by: string;             // 요청 IP (로그인이 없다)
    retired_at: string | null;
}

export interface CustomerTimeline {
    sender: string;
    total: number;
    next_before: string | null;     // 있으면 이 시각보다 이전 문의가 더 있다
    items: TimelineInquiry[];       // 수신 시각 오름차순 (오래된 것이 위)
}
