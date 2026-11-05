/** RAG 업로드/질의 API 클라이언트. 베이스 URL 규칙은 lib/http.ts 참고. */
import { API_BASE, ApiError, request } from '../lib/http';
import type { AppConfig, AskRequest, AskResponse, FileDetail, FileGroup, FileSummary, UploadResponse } from './types';

export const ragApi = {
    /** 서버 설정 (Claude 모드 사용 가능 여부) */
    getConfig(): Promise<AppConfig> {
        return request<AppConfig>('/config');
    },

    /** 서버에 저장된 파일 목록 */
    listFiles(): Promise<FileSummary[]> {
        return request<FileSummary[]>('/files');
    },

    getFileDetail(fileId: string): Promise<FileDetail> {
        return request<FileDetail>(`/file/${encodeURIComponent(fileId)}`);
    },

    /** 사용자가 만든 문서 그룹 목록과 그룹별 파일 수 */
    listGroups(): Promise<FileGroup[]> {
        return request<FileGroup[]>('/groups');
    },

    createGroup(name: string, description: string): Promise<FileGroup> {
        return request<FileGroup>('/groups', {
            method: 'POST',
            body: JSON.stringify({ name, description }),
        });
    },

    updateGroup(groupId: string, changes: { name?: string; description?: string }): Promise<FileGroup> {
        return request<FileGroup>(`/groups/${encodeURIComponent(groupId)}`, {
            method: 'PATCH',
            body: JSON.stringify(changes),
        });
    },

    updateFileDescription(fileId: string, description: string): Promise<{ file_id: string; description: string }> {
        return request(`/file/${encodeURIComponent(fileId)}/description`, {
            method: 'PATCH',
            body: JSON.stringify({ description }),
        });
    },

    /** 파일의 문서 그룹 변경. null 이면 미분류로 되돌린다. 검색용 청크 메타데이터도 서버가 같이 바꾼다 */
    setFileGroup(fileId: string, groupId: string | null): Promise<{ file_id: string; group_id: string | null; updated_chunks: number }> {
        return request(`/file/${encodeURIComponent(fileId)}/group`, {
            method: 'PUT',
            body: JSON.stringify({ group_id: groupId }),
        });
    },

    filePreviewUrl(fileId: string): string {
        return `${API_BASE}/file/${encodeURIComponent(fileId)}/preview`;
    },

    /** 원본 PDF를 읽는다. 선택이 바뀌면 진행 중인 요청을 취소할 수 있다. */
    async previewPdf(fileId: string, signal: AbortSignal): Promise<Blob> {
        const response = await fetch(ragApi.filePreviewUrl(fileId), { signal });
        if (!response.ok) {
            let message = 'PDF를 불러오지 못했습니다.';
            try {
                const body = await response.json();
                if (typeof body.detail === 'string') message = body.detail;
            } catch {
                /* JSON 오류 응답이 아니면 기본 안내를 사용한다. */
            }
            throw new ApiError(response.status, message);
        }
        const blob = await response.blob();
        if (blob.type.split(';')[0] !== 'application/pdf') {
            throw new Error('서버에서 PDF 원본을 제공하지 못했습니다.');
        }
        return blob;
    },

    /** 여러 파일을 한 번에 같은 그룹으로 이동. null 이면 미분류 */
    setFilesGroup(fileIds: string[], groupId: string | null): Promise<{ updated: number; group_id: string | null; updated_chunks: number }> {
        return request('/files/group', {
            method: 'PUT',
            body: JSON.stringify({ file_ids: fileIds, group_id: groupId }),
        });
    },

    /** 파일 삭제 (원본 + 임베딩) */
    deleteFile(fileId: string): Promise<unknown> {
        return request<unknown>(`/file/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
    },

    /** 문서 업로드 → 파싱/청킹/임베딩 후 벡터 저장소에 저장. groupId 를 주면 모든 파일이 그 그룹으로 들어간다 */
    upload(files: File[], groupId: string | null = null, descriptions: string[] = []): Promise<UploadResponse> {
        const form = new FormData();
        for (const f of files) form.append('files', f);
        if (groupId) form.append('group_id', groupId);
        for (const description of descriptions) form.append('descriptions', description);
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
