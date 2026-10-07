/** RAG 업로드/질의 API 클라이언트. 베이스 URL 규칙은 lib/http.ts 참고. */
import { request } from '../lib/http';
import type { AskRequest, AskResponse, FileSummary, UploadResponse } from './types';

export const ragApi = {
    /** 서버에 저장된 파일 목록 */
    listFiles(): Promise<FileSummary[]> {
        return request<FileSummary[]>('/files');
    },

    /** 파일 삭제 (원본 + 임베딩) */
    deleteFile(fileId: string): Promise<unknown> {
        return request<unknown>(`/file/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
    },

    /** 문서 업로드 → 파싱/청킹/임베딩 후 벡터 저장소에 저장 */
    upload(files: File[]): Promise<UploadResponse> {
        const form = new FormData();
        for (const f of files) form.append('files', f);
        return request<UploadResponse>('/upload', { method: 'POST', body: form });
    },

    /** 업로드된 문서를 근거로 RAG 에이전트가 답변 생성 */
    ask(payload: AskRequest): Promise<AskResponse> {
        return request<AskResponse>('/ask', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },
};
