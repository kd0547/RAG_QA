/**
 * 용어집 API 클라이언트 (백엔드: app/routers/terms.py, /graph/terms).
 *
 * 용어집은 사람이 관리하는 회사 용어다. 문서 그래프에는 쓰지 않고, 그래프 검색이 질문을 읽을 때만 쓴다.
 */
import { API_BASE, request } from '../../lib/http';

export type TargetType = '' | 'entity_type' | 'spec_attribute';
/** bundle: 구성 용어가 있는 용어 (예: KC 인증 자료 = 적합성 등록 + 안전확인 신고). 묶음 안에 묶음은 없다 */
export type TermKind = 'term' | 'bundle';

export interface TermRef {
    id: number;
    name: string;
}

export interface Term {
    id: number;
    name: string;
    /** 표준 이름을 뺀 다른 표기 */
    aliases: string[];
    target_type: TargetType;
    target_key: string;
    target_label: string;
    /** "그래프:인증", "사양:메모리 용량" (없으면 '') */
    target_text: string;
    description: string;
    created_at: string;
    updated_at: string;
    kind: TermKind;
    /** 묶음이면 구성 용어 */
    members: TermRef[];
    /** 이 용어가 들어 있는 묶음 */
    bundles: TermRef[];
}

export interface TermInput {
    name: string;
    aliases: string[];
    target_type: TargetType;
    target_key: string;
    description: string;
    /** 구성 용어 id. 있으면 묶음, []면 묶음을 푼다 */
    members: number[];
}

export interface TargetOption {
    key: string;
    label: string;
    category?: string;
}

export interface TermTargets {
    entity_type: TargetOption[];
    spec_attribute: TargetOption[];
}

export interface ResolvedPart extends Omit<Term, 'aliases' | 'members' | 'bundles' | 'kind'> {
    /** 표준 이름을 포함한 모든 표기 */
    aliases: string[];
    graph_entities: { id: number; type: string; name: string }[];
}

export interface ResolvedTerm extends ResolvedPart {
    kind: TermKind;
    /** 질문에 나온 표기 */
    matched: string;
    /** 묶음이면 구성 용어 (구성 용어마다 그 표기로 찾은 그래프 개체) */
    members: ResolvedPart[];
}

export type ImportStatus = 'new' | 'update' | 'unchanged' | 'conflict' | 'error' | 'skip';

export interface ImportRow {
    line: number | null;
    name: string;
    aliases: string[];
    /** '용어' | '묶음' | '' (비우면 구성 용어가 있을 때 묶음) */
    kind: string;
    /** 구성 용어 이름 (같은 표의 행이나 등록된 용어) */
    members: string[];
    target: string;
    description: string;
    skip: boolean;
}

export interface PlannedRow extends ImportRow {
    index: number;
    status: ImportStatus;
    term_id: number | null;
    term_name: string | null;
    added_aliases: string[];
    changes: string[];
    messages: string[];
}

export interface ImportPlan {
    source: string;
    rows: PlannedRow[];
    counts: Partial<Record<ImportStatus, number>>;
}

export interface ImportSummary {
    created: number;
    updated: number;
    unchanged: number;
    skipped: number;
}

/** 다른 표기 칸: 쉼표·줄바꿈으로 나눈다 (엑셀 양식과 같다) */
export function splitAliases(text: string): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const part of text.split(/[,\n;，、]/)) {
        const alias = part.split(/\s+/).filter(Boolean).join(' ');
        const key = alias.toLowerCase().replace(/[\s_\-·.,:/()[\]]+/g, '');
        if (alias && !seen.has(key)) {
            seen.add(key);
            result.push(alias);
        }
    }
    return result;
}

/** 미리보기 행에서 서버에 다시 보낼 부분만 */
export function toImportRow(row: ImportRow): ImportRow {
    return {
        line: row.line, name: row.name, aliases: row.aliases, kind: row.kind, members: row.members,
        target: row.target, description: row.description, skip: row.skip,
    };
}

export const termApi = {
    list(q?: string) {
        const query = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
        return request<Term[]>(`/graph/terms${query}`);
    },
    targets() {
        return request<TermTargets>('/graph/terms/targets');
    },
    resolve(q: string) {
        return request<{ query: string; terms: ResolvedTerm[] }>(`/graph/terms/resolve?q=${encodeURIComponent(q)}`);
    },
    create(input: TermInput) {
        return request<Term>('/graph/terms', { method: 'POST', body: JSON.stringify(input) });
    },
    update(id: number, input: Partial<TermInput>) {
        return request<Term>(`/graph/terms/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
    },
    remove(id: number) {
        return request<void>(`/graph/terms/${id}`, { method: 'DELETE' });
    },
    templateUrl() {
        return `${API_BASE}/graph/terms/template`;
    },
    parse(source: { file: File } | { text: string }) {
        const form = new FormData();
        if ('file' in source) form.append('file', source.file);
        else form.append('text', source.text);
        return request<ImportPlan>('/graph/terms/import/parse', { method: 'POST', body: form });
    },
    check(source: string, rows: ImportRow[]) {
        return request<ImportPlan>('/graph/terms/import/check', { method: 'POST', body: JSON.stringify({ source, rows: rows.map(toImportRow) }) });
    },
    apply(source: string, rows: ImportRow[]) {
        return request<ImportSummary>('/graph/terms/import/apply', { method: 'POST', body: JSON.stringify({ source, rows: rows.map(toImportRow) }) });
    },
};
