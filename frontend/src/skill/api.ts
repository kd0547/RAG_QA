/**
 * SKILL API 클라이언트 (백엔드: app/routers/skills.py). 화면 경로는 /skill, API는 /skills.
 * 베이스 URL 규칙은 lib/http.ts 참고.
 */
import { request } from '../lib/http';

export type SkillOrigin = 'repo' | 'db';
export type DocStatus = 'generating' | 'draft' | 'approved' | 'rejected' | 'retired' | 'error';
export type TypeState = 'open' | 'no_skill_needed' | 'merged';

export interface AuthorStatus {
    available: boolean;
    name: string;
    digest: string | null;
    reason: string | null;
}

export interface TypeRef {
    type_id: number;
    label: string | null;
    state?: TypeState | null;
}

export interface SkillItem {
    name: string;
    description: string;
    channels: string[];
    origin: SkillOrigin;
    version: number | null;
    digest: string;
    author: boolean;          // 작성 SKILL(author 채널, create-skill). 답변 SKILL이 아니다
    enabled: boolean;         // 저장소 SKILL을 끄면 false (DB SKILL은 늘 true — 멈출 때는 사용 중지)
    disabled_at: string | null;
    files: string[];          // 참고 파일 (references/·templates/)
    uses_30d: number;
    doc_id: number | null;
    type: TypeRef | null;
    approved_at: string | null;
}

export interface SkillList {
    items: SkillItem[];
    load_errors: { folder: string; reason: string }[];  // skills/ 폴더에 있지만 검사를 통과하지 못해 뺀 문서
    loaded_at: string | null;                            // 저장소 SKILL을 마지막으로 읽은 시각
    author: AuthorStatus;
    settings: { analysis_enabled: boolean; auto_draft: boolean; min_cases: number; usage_days: number };
}

export interface HistoryItem {
    doc_id: number;
    version: number;
    status: DocStatus;
    origin: 'generated' | 'edited';
    digest: string | null;
    created_at: string;
    reviewed_at: string | null;
    reviewed_by: string | null;
    review_note: string | null;
}

export interface SkillDetail {
    name: string;
    description: string | null;
    channels: string[];
    origin: SkillOrigin;
    version: number | null;
    digest: string | null;
    body: string | null;
    read_only: boolean;
    active: boolean;
    doc_id?: number;
    type?: TypeRef | null;
    open_draft?: { doc_id: number; version: number } | null;
    history: HistoryItem[];
    // 저장소 SKILL만
    author?: boolean;
    enabled?: boolean;
    disabled_at?: string | null;
    disabled_by?: string | null;
    files?: string[];
}

export interface CheckResult {
    ok: boolean;
    errors: string[];
    warnings: string[];
}

export interface DraftItem {
    doc_id: number;
    name: string | null;   // 생성 중·생성 실패 초안은 이름이 없다
    version: number | null;
    status: DocStatus;
    origin: 'generated' | 'edited';
    type: TypeRef | null;
    created_at: string;
    check: { ok: boolean; errors: number; warnings: number } | null;
    error: string | null;
    description: string | null;
}

export interface CaseSummary {
    task_id: string;
    subject: string;
    status: string;
    received_at: string;
    sent: boolean;
}

export interface DraftDetail extends Omit<DraftItem, 'check'> {
    body: string | null;
    check: CheckResult | null;
    cases: CaseSummary[];
    base_version: number | null;
    reviewed_at: string | null;
    reviewed_by: string | null;
    review_note: string | null;
    model: string | null;
    already?: boolean;
}

export interface RequestType {
    type_id: number;
    label: string;
    description: string;
    skill_name: string | null;
    state: TypeState;
    merged_into: number | null;
    origin: 'seed' | 'model';
    case_count: number;
    mismatch_count: number;
    recent_cases: { task_id: string; status: string; subject: string; received_at: string }[];
    open_drafts: { doc_id: number; status: DocStatus; name: string | null }[];
    has_rejected: boolean;
    created_at: string;
}

export interface TypeList {
    items: RequestType[];
    author: AuthorStatus;
    analysis: { total: number; errors: number };
}

export interface AnalysisItem {
    task_id: string;
    subject: string;
    task_status: string;
    received_at: string;
    status: 'ok' | 'error';
    type: { type_id: number; label: string | null } | null;
    covered_by: string | null;
    used_skills: string[];
    mismatch: boolean;
    reason: string | null;
    error: string | null;
    attempts: number;
    analyzed_at: string;
}

const enc = encodeURIComponent;
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body ?? {}) });

export const skillApi = {
    list: () => request<SkillList>('/skills'),
    get: (name: string) => request<SkillDetail>(`/skills/${enc(name)}`),
    newVersion: (name: string) => request<DraftDetail>(`/skills/${enc(name)}/drafts`, { method: 'POST' }),
    retire: (name: string) => request<SkillDetail>(`/skills/${enc(name)}/retire`, { method: 'POST' }),
    // 저장소 SKILL 끄기·다시 켜기 (파일은 그대로)
    disable: (name: string) => request<SkillDetail>(`/skills/${enc(name)}/disable`, { method: 'POST' }),
    enable: (name: string) => request<SkillDetail>(`/skills/${enc(name)}/enable`, { method: 'POST' }),

    drafts: (status?: DocStatus[]) =>
        request<{ items: DraftItem[]; author: AuthorStatus }>(
            `/skills/drafts${status?.length ? `?status=${enc(status.join(','))}` : ''}`,
        ),
    draft: (docId: number) => request<DraftDetail>(`/skills/drafts/${docId}`),
    saveDraft: (docId: number, input: { description: string; body: string }) =>
        request<DraftDetail>(`/skills/drafts/${docId}`, { method: 'PUT', body: JSON.stringify(input) }),
    approve: (docId: number, note: string) => request<DraftDetail>(`/skills/drafts/${docId}/approve`, json({ note })),
    reject: (docId: number, reason: string) => request<DraftDetail>(`/skills/drafts/${docId}/reject`, json({ reason })),

    types: () => request<TypeList>('/skills/types'),
    requestDraft: (typeId: number) =>
        request<{ doc_id: number; already: boolean; message: string }>(`/skills/types/${typeId}/draft`, { method: 'POST' }),
    setTypeState: (typeId: number, state: 'open' | 'no_skill_needed') =>
        request<RequestType>(`/skills/types/${typeId}/state`, json({ state })),
    mergeType: (typeId: number, into: number) => request<unknown>(`/skills/types/${typeId}/merge`, json({ into })),

    analysis: (params: { typeId?: number; mismatch?: boolean; limit?: number } = {}) => {
        const q = new URLSearchParams();
        if (params.typeId != null) q.set('type_id', String(params.typeId));
        if (params.mismatch != null) q.set('mismatch', String(params.mismatch));
        if (params.limit != null) q.set('limit', String(params.limit));
        const qs = q.toString();
        return request<{ items: AnalysisItem[]; total: number }>(`/skills/analysis${qs ? `?${qs}` : ''}`);
    },
};
