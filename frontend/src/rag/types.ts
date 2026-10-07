/**
 * RAG 업로드/질의 API 타입.
 * 계약: app/routers/files.py (POST /upload, GET /files), app/routers/questions.py (POST /ask)
 */

/** GET /files 의 항목. repository/file_repository.py file_list() */
export interface FileSummary {
    file_id: string;
    original_name: string;
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
    num_chunks?: number;
    chunks_saved_to?: string;
    chunks?: ChunkPreview[];
}

export interface UploadResponse {
    results: UploadResult[];
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

export interface AskResponse {
    question: string;
    answer: string;
    sources: AskSource[];
}
