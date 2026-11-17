/**
 * 질의응답 대화 기록 (화면 밖 저장소 + 브라우저 localStorage).
 *
 * 질의응답 화면은 다른 페이지(제품 사양 등)로 가면 닫히므로, 대화를 여기에 둬서 돌아와도 남게 한다.
 * 답을 기다리는 중에 다른 페이지로 가도 답이 오면 여기에 들어가 돌아왔을 때 보인다.
 * - localStorage에는 최근 MAX_TURNS개만 저장한다. 첨부는 이름·크기만 (파일과 이미지 미리보기는 새로고침하면 없다)
 * - 답을 기다리던 중 새로고침하면 그 질문은 실패로 표시한다
 * - 저장소는 각자의 브라우저다. 서버에는 저장하지 않는다
 */
import type { AnswerRating, AskMode, AskSource } from './types';

/** 보낸 질문에 붙였던 파일. previewUrl은 이 페이지를 연 동안만 있다 (이미지 object URL) */
export interface SentAttachment {
    id: string;
    name: string;
    size: number;
    isImage: boolean;
    previewUrl: string | null;
}

export interface QaTurn {
    id: string;
    question: string;
    mode: AskMode;
    queryTopN: number;
    rerankTopN: number;
    askedAt: string;
    attachments: SentAttachment[];
    status: 'pending' | 'done' | 'error';
    answer?: string;
    sources?: AskSource[];
    error?: string;
    /** 서버 질의응답 로그 ID. 있으면 답변 아래에 평가 버튼이 나온다 */
    logId?: string | null;
    /** 서버에 저장된 평가 (화면에 다시 그리기 위한 사본) */
    rating?: AnswerRating | null;
    comment?: string;
}

const STORAGE_KEY = 'tg-rag.qa-turns.v1';
const MAX_TURNS = 50;
const RELOADED_ERROR = '새로고침으로 답변을 받지 못했습니다. 다시 질문해 주세요.';

function releaseTurns(list: QaTurn[]) {
    for (const t of list) for (const a of t.attachments) if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
}

function load(): QaTurn[] {
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const list: unknown = JSON.parse(raw);
        if (!Array.isArray(list)) return [];
        return (list as QaTurn[])
            .filter((t) => t && typeof t.id === 'string' && typeof t.question === 'string')
            .map((t) => ({
                ...t,
                attachments: (t.attachments ?? []).map((a) => ({ ...a, previewUrl: null })),
                ...(t.status === 'pending' ? { status: 'error' as const, error: RELOADED_ERROR } : {}),
            }));
    } catch {
        return [];
    }
}

function save(list: QaTurn[]) {
    const stored = list.map((t) => ({ ...t, attachments: t.attachments.map((a) => ({ ...a, previewUrl: null })) }));
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch {
        // 용량 초과면 오래된 절반을 버리고 한 번 더 시도한다. 저장이 막힌 브라우저면 이 페이지를 연 동안만 남는다
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stored.slice(Math.floor(stored.length / 2))));
        } catch { /* 저장 불가 */ }
    }
}

let turns: QaTurn[] = load();
const listeners = new Set<() => void>();

function commit(next: QaTurn[]) {
    if (next.length > MAX_TURNS) {
        releaseTurns(next.slice(0, next.length - MAX_TURNS));
        next = next.slice(-MAX_TURNS);
    }
    turns = next;
    save(turns);
    for (const listener of listeners) listener();
}

export const qaHistory = {
    subscribe(listener: () => void) {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
    },
    getSnapshot(): QaTurn[] {
        return turns;
    },
    update(fn: (prev: QaTurn[]) => QaTurn[]) {
        commit(fn(turns));
    },
    /** 대화 초기화: 화면과 브라우저에 저장된 기록을 모두 지운다 */
    clear() {
        releaseTurns(turns);
        commit([]);
    },
};
