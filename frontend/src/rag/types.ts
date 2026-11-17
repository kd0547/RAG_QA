/**
 * RAG 업로드/질의 API 타입.
 * 계약: app/routers/files.py (POST /upload, GET /files), app/routers/questions.py (POST /ask, POST /ask/attachments)
 */

/**
 * 문서 검수 상태. 업로드는 파싱까지만 하고 pending으로 둔다.
 * 파일 검수에서 [검수 완료]를 눌러야 청킹·임베딩·그래프 추출을 하고 done이 된다.
 * pending 문서는 질의응답 검색·문서 도구·그래프에 쓰이지 않는다.
 */
export type ReviewStatus = 'pending' | 'done';

/** GET /files 의 항목. repository/file_repository.py file_list() */
export interface FileSummary {
    file_id: string;
    original_name: string;
    /** 문서 그룹(GET /groups 의 id). null 이면 아직 분류하지 않은 파일 */
    group_id: string | null;
    description: string;
    review_status: ReviewStatus;
    /** [검수 완료] 뒤 검색 반영이 실패했을 때의 원인. 다시 시도하면 지워진다 */
    error_message: string | null;
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

/**
 * GET /file/{id}/pages 의 항목 (파일 검수). repository/file_page_repository.py
 * 업로드 때 파서가 뽑은 페이지별 텍스트다. xlsx는 같은 page에 블록이 여럿일 수 있다.
 */
export interface FilePage {
    page_id: number;
    seq: number;
    /** 1부터 시작하는 페이지(시트) 번호 */
    page: number;
    /** 검색에 쓰는 현재 텍스트 (검수로 수정) */
    text: string;
    /** 업로드 때 파싱 결과. 서버가 바꾸지 않는다 */
    original_text: string;
    edited: boolean;
    updated_at: string;
}

export interface FilePagesResponse {
    file_id: string;
    original_name: string;
    review_status: ReviewStatus;
    error_message: string | null;
    pages: FilePage[];
}

/**
 * PUT /file/{id}/pages/{page_id} — chunk_count는 다시 만든 청크 수.
 * 내용이 같거나 검수 대기 파일(아직 색인 전)이면 null
 */
export interface PageUpdateResponse {
    page: FilePage;
    chunk_count: number | null;
}

/** POST /file/{id}/review/complete — 검수한 페이지 텍스트 전체를 검색에 반영한 결과 */
export interface ReviewCompleteResponse {
    file_id: string;
    review_status: 'done';
    chunk_count: number;
}

/**
 * 파일 하나의 업로드 결과. 개별 파일이 실패하면 error만 채워져서 온다.
 * 성공하면 파싱까지만 끝난 검수 대기(review_status = pending) 상태다.
 */
export interface UploadResult {
    filename: string;
    error?: string;
    /** 동일한 내용이 이미 등록된 파일은 다시 등록하지 않는다. */
    skipped?: 'duplicate';
    file_id?: string;
    review_status?: 'pending';
    /** 파싱한 페이지(시트) 수 */
    num_pages?: number;
    /** 파싱한 글자 수 (앞뒤 공백 제외). 0이면 텍스트를 뽑지 못했다 */
    num_chars?: number;
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
    /** 서버 질의응답 로그 ID. 평가(POST /ask/feedback)에 쓴다. 로그를 못 남겼으면 null */
    log_id?: string | null;
}

export type AnswerRating = 'good' | 'bad';
