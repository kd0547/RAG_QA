/** 프롬프트 설정 API 클라이언트 (백엔드: app/routers/prompt.py). 베이스 URL 규칙은 lib/http.ts 참고. */
import { request } from '../lib/http';

export interface Prompt {
    id: number;
    name: string;
    content: string;
    is_default: boolean;   // 서버가 처음 넣는 기본 프롬프트 (삭제 불가)
    is_selected: boolean;  // 에이전트가 쓰는 프롬프트 (항상 하나)
    created_at: string;
    updated_at: string;
}

export interface PromptInput {
    name: string;
    content: string;
}

const path = (id: number) => `/prompts/${encodeURIComponent(String(id))}`;

export const promptApi = {
    list(): Promise<Prompt[]> {
        return request<Prompt[]>('/prompts');
    },

    create(input: PromptInput): Promise<Prompt> {
        return request<Prompt>('/prompts', { method: 'POST', body: JSON.stringify(input) });
    },

    update(id: number, input: PromptInput): Promise<Prompt> {
        return request<Prompt>(path(id), { method: 'PUT', body: JSON.stringify(input) });
    },

    /** 선택된 프롬프트를 지우면 서버가 기본 프롬프트를 선택한다 */
    remove(id: number): Promise<void> {
        return request<void>(path(id), { method: 'DELETE' });
    },

    /** 이 프롬프트를 사용한다. 기존 선택은 서버가 해제한다 */
    select(id: number): Promise<Prompt> {
        return request<Prompt>(`${path(id)}/select`, { method: 'POST' });
    },
};
