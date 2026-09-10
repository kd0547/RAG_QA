// ===== 서버 응답 (API contract) =====
export interface OcrBlock {
    index: number | null;
    label: string | null;
    bbox: [number, number, number, number]; // [x1, y1, x2, y2] (원본 픽셀 좌표)
    content: string;
}

/** markdown 본문 내 상대경로 이미지(imgs/...)에 대응하는 base64 데이터 */
export interface OcrMarkdownImage {
    path: string;
    image: string; // data:image/...;base64,...
}

export interface OcrPageInfo {
    index: number;
    type: string;
    filename: string;
    markdown: string;
    markdown_images: OcrMarkdownImage[];
    source_image: string;
    size: number;
    blocks: OcrBlock[];
}

export interface OcrFileResult {
    filename: string;
    fileinfo: OcrPageInfo[];
}

export interface OcrResponse {
    results: OcrFileResult[];
}

export interface OcrFile {
    id: string;
    file: File;
    name: string;
    type: string;
    size: number;
    status: FileStatus;
    /** 페이지별 결과 (이미지는 길이 1, PDF는 N) */
    pages: OcrPageInfo[];
    error: string;
}

/** 선택 상태: pageIndex === null 이면 파일 전체 보기 */
export interface Selection {
    fileId: string;
    pageIndex: number | null;
}

export type FileStatus = 'pending' | 'processing' | 'done' | 'error';
export type PreviewMode = 'markdown' | 'html';


export type CopyStatus = '' | 'copied' | 'failed';

