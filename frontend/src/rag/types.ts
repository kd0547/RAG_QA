/**
 * RAG 업로드/질의 API 타입.
 * 계약: app/routers/files.py (POST /upload, GET /files), app/routers/questions.py (POST /ask, POST /ask/attachments)
 */

/** GET /files 의 항목. repository/file_repository.py file_list() */
export interface FileSummary {
    file_id: string;
    original_name: string;
    /** 문서 그룹(GET /groups 의 id). null 이면 아직 분류하지 않은 파일 */
    group_id: string | null;
    description: string;
}

/** GET/POST /groups 및 PATCH /groups/{id} 의 항목. 파일을 모으는 사용자 생성 그룹 */
export interface FileGroup {
    id: string;
    name: string;
    description: string;
    file_count: number;
    created_at?: string;
    updated_at?: string;
}

/** GET /file/{file_id} — 파일 상세의 기본 정보 */
export interface FileDetail extends FileSummary {
    mime_type: string | null;
    size_bytes: number | null;
    chunk_count: number | null;
    created_at: string | null;
    updated_at: string | null;
}

/** retrieval/type.py 의 Chunk — 응답에서는 embedding 벡터가 빠진 미리보기용으로 온다 */
export interface ChunkPreview {
    id: string;
    source: string;
    page: number;
    chunk_index: number;
    text: string;
    chunk_type: string;
}

/** 파일 하나의 처리 결과. 개별 파일이 실패하면 error만 채워져서 온다 */
export interface UploadResult {
    filename: string;
    error?: string;
    /** 동일한 내용이 이미 등록된 파일은 다시 인덱싱하지 않는다. */
    skipped?: 'duplicate';
    num_chunks?: number;
    chunks_saved_to?: string;
    chunks?: ChunkPreview[];
}

export interface UploadResponse {
    results: UploadResult[];
}

/** GET /config — 서버에 ANTHROPIC_API_KEY가 있으면 claude_available = true */
export interface AppConfig {
    claude_available: boolean;
}

/** claude = Claude API, local = 로컬(vLLM/Ollama) 모델 */
export type AskMode = 'claude' | 'local';

export interface AskRequest {
    question: string;
    mode: AskMode;
    query_top_n: number;
    rerank_top_n: number;
}

export interface AskSource {
    source: string;
    page: number;
    text: string;
}

/** 질문에 붙여 보낸 첨부 (POST /ask/attachments 응답에만 있다) */
export interface AskAttachmentInfo {
    filename: string;
    /** image | pdf | docx | pptx | xlsx | hwp | hwpx */
    type: string;
}

export interface AskResponse {
    question: string;
    answer: string;
    sources: AskSource[];
    attachments?: AskAttachmentInfo[];
}
