# TG OCR — Frontend

이미지/PDF를 업로드하면 OCR 서버에 전송해 마크다운 결과를 받아오는 React 기반 프런트엔드입니다. 결과는 원본 이미지 위에 OCR 블록(bbox) 오버레이로 확인할 수 있고, WYSIWYG 에디터로 즉시 수정한 뒤 Markdown/HTML로 복사·다운로드할 수 있습니다.

## 기술 스택

- React 19 + TypeScript, Vite 8
- Tailwind CSS 4 (`@tailwindcss/vite`)
- [`@mdxeditor/editor`](https://mdxeditor.dev/) — Markdown WYSIWYG 편집기
- `react-markdown` + `remark-gfm` + `rehype-raw`/`rehype-sanitize` — Markdown → HTML 미리보기/변환
- `jszip` — Markdown + 이미지 zip 다운로드

## 실행 방법

```bash
npm install
npm run dev      # http://localhost:5173
```

| 명령어 | 설명 |
| --- | --- |
| `npm run dev` | 개발 서버 실행 (HMR) |
| `npm run build` | `tsc -b` 타입체크 + `vite build` (→ `dist/`) |
| `npm run preview` | 빌드 결과물 로컬 프리뷰 |
| `npm run lint` | ESLint 검사 |

OCR API 서버가 별도로 `http://127.0.0.1:8082`에서 떠 있어야 업로드 기능이 동작합니다 (아래 [OCR API 서버 설정](#ocr-api-서버-설정) 참고).

## 주요 기능

### 1. 파일 업로드
- 좌측 사이드바의 드롭존을 클릭하거나 이미지/PDF 파일을 드래그 앤 드롭
- 이미지 붙여넣기(Ctrl+V)도 지원 — 클립보드의 이미지를 자동으로 파일 목록에 추가
- 여러 파일 동시 업로드 가능, 각 파일은 추가되는 즉시 개별적으로 OCR API를 호출
- `image/*` 또는 `application/pdf` MIME 타입만 허용

### 2. 파일 목록 & 상태 관리
- 업로드된 파일은 카드 형태로 좌측에 나열되며 상태(대기/처리 중/완료/실패)를 뱃지로 표시
- PDF이고 페이지가 2개 이상이면 카드를 펼쳐 페이지별로 개별 선택 가능
- 실패한 파일은 재시도(Retry) 버튼 제공, 개별 삭제 가능

### 3. OCR 결과 보기 (Source Image)
- 원본 이미지 위에 OCR이 인식한 블록(bbox)을 SVG 오버레이로 표시 (`Boxes` 토글로 표시/숨김)
- 블록에 마우스를 올리면 해당 블록의 `label`/`content`가 툴팁으로 표시
- bbox 좌표는 정규화(0~1) 또는 원본 픽셀 좌표 어느 쪽이든 자동 인식해서 렌더링

### 4. Markdown 편집 / HTML 미리보기
- 이미지 1장 또는 PDF 개별 페이지를 선택하면 MDXEditor 기반 WYSIWYG 에디터로 즉시 편집 가능
- 편집 결과는 즉시 해당 페이지의 `markdown`에 반영되어 복사/다운로드/HTML 변환에 자동으로 따라감
- PDF 전체(합본) 보기는 읽기 전용 미리보기만 제공 (편집하려면 개별 페이지 선택 필요)
- `Markdown`/`HTML` 탭 전환 — HTML 탭은 마크다운을 sanitize된 HTML 문서로 변환해 iframe으로 렌더링

### 5. 복사 / 다운로드
- **복사**: 현재 화면(Markdown 텍스트 또는 렌더링된 HTML 문서)을 클립보드로 복사
- **현재 항목 저장**:
  - Markdown 모드 → `.md` 파일 + 참조된 이미지들을 묶은 `.zip` 다운로드
  - HTML 모드 → 이미지가 base64로 인라인된 단일 `.html` 파일 다운로드
- **전체 다운로드**: 완료된 모든 파일을 순차적으로 개별 다운로드 (PDF는 페이지를 합쳐 파일 1개로 저장)

## OCR API 서버 설정

현재 API 엔드포인트는 [`src/App.tsx`](src/App.tsx)의 `runOcr` 함수에 하드코딩되어 있습니다.

```ts
const response = await fetch('http://127.0.0.1:8082/ocr/run_ocr', {
    method: 'POST',
    body: formData,
});
```

다른 호스트/포트를 쓰거나 `rag_QA` 백엔드와 연동하려면 이 URL을 환경변수(`import.meta.env.VITE_OCR_API_URL` 등)로 분리하는 것을 권장합니다.

## API 연동 상세

### `POST /ocr/run_ocr`

파일을 하나 업로드할 때마다 아래 요청이 1회 호출됩니다 (여러 파일을 한 번에 올려도 파일별로 개별 요청).

**Request**

- `Content-Type: multipart/form-data`
- Body: `FormData`

| 필드명 | 타입 | 설명 |
| --- | --- | --- |
| `files` | `File` | 업로드할 이미지 또는 PDF 파일 1개 |

```js
const formData = new FormData();
formData.append('files', file); // image/* 또는 application/pdf
```

**Response** — `200 OK`, `Content-Type: application/json`

```ts
interface OcrResponse {
  results: OcrFileResult[];
}

interface OcrFileResult {
  filename: string;
  fileinfo: OcrPageInfo[];   // 이미지=1개, PDF=페이지 수만큼
}

interface OcrPageInfo {
  index: number;                       // 페이지 순번 (0부터)
  type: string;                        // 페이지 타입 (예: "page")
  filename: string;                    // 페이지 파일명
  markdown: string;                    // OCR 결과 마크다운 본문
  markdown_images: OcrMarkdownImage[]; // markdown 내 상대경로 이미지에 대응하는 base64 데이터
  source_image: string;                // 원본 페이지 이미지 (data URI 또는 URL)
  size: number;                        // 페이지 크기(바이트 등)
  blocks: OcrBlock[];                  // OCR이 인식한 블록(bbox) 목록
}

interface OcrMarkdownImage {
  path: string;   // markdown 안의 상대경로 (예: "imgs/img_0.png")
  image: string;  // "data:image/png;base64,...."
}

interface OcrBlock {
  index: number | null;
  label: string | null;                       // 예: "title", "text", "table"
  bbox: [number, number, number, number];      // [x1, y1, x2, y2] — 정규화(0~1) 또는 원본 픽셀 좌표
  content: string;                             // 해당 블록의 인식 텍스트
}
```

**Response 예시**

```json
{
  "results": [
    {
      "filename": "report.pdf",
      "fileinfo": [
        {
          "index": 0,
          "type": "page",
          "filename": "report_page_1.png",
          "markdown": "## 보고서 1\n\n본문 테스트 문단입니다. **굵게** 그리고 *기울임*.\n\n![다이어그램](imgs/img_0.png)\n\n| 항목 | 값 |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n",
          "markdown_images": [
            {
              "path": "imgs/img_0.png",
              "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
            }
          ],
          "source_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
          "size": 254123,
          "blocks": [
            { "index": 0, "label": "title", "bbox": [0.05, 0.03, 0.9, 0.09], "content": "보고서 1" },
            { "index": 1, "label": "text",  "bbox": [0.05, 0.11, 0.9, 0.18], "content": "본문 테스트 문단입니다." },
            { "index": 2, "label": "table", "bbox": [0.05, 0.30, 0.9, 0.55], "content": "항목 | 값\nA | 1\nB | 2" }
          ]
        }
      ]
    }
  ]
}
```

**에러 처리**

- `response.ok`가 아니면(`4xx`/`5xx`) `Error(\`Server responded with ${status}\`)`를 던지고 해당 파일 상태를 `error`로 표시합니다.
- 네트워크 오류(fetch 자체 실패, 서버 다운 등)도 동일하게 `error` 상태로 처리되며, 에러 메시지가 UI에 노출됩니다.
- 실패한 파일은 카드의 재시도 버튼으로 동일 요청을 다시 보낼 수 있습니다.

### 좌표계 규칙 (`OcrBlock.bbox`)

`ImageWithBoxes` 컴포넌트가 다음 규칙으로 자동 판별합니다:

- `bbox`의 네 값이 모두 `1.5` 이하이면 **정규화 좌표(0~1)**로 간주하고 원본 이미지 크기(`naturalWidth/Height`)를 곱해 픽셀 좌표로 변환
- 그 외에는 **원본 픽셀 좌표**로 간주해 그대로 사용
- `[x1, y1, x2, y2]` 순서이며 좌표가 뒤바뀌어 있어도(`x2 < x1` 등) `min/abs`로 보정

## 데이터 흐름 (프런트엔드 내부 상태)

```
파일 업로드
  → handleAddFiles(): OcrFile 생성 (status: 'pending')
  → runOcr(): status → 'processing' → POST /ocr/run_ocr
       성공 → status: 'done', pages: OcrPageInfo[]
       실패 → status: 'error', error: string
```

```ts
interface OcrFile {
  id: string;            // 클라이언트 생성 고유 ID
  file: File;             // 원본 File 객체 (재시도 시 재사용)
  name: string;
  type: string;           // MIME 타입
  size: number;
  status: 'pending' | 'processing' | 'done' | 'error';
  pages: OcrPageInfo[];    // 이미지=1개, PDF=페이지 수만큼
  error: string;
}
```

## 프로젝트 구조

```
frontend/
├── index.html
├── src/
│   ├── main.tsx                    # 엔트리포인트
│   ├── App.tsx                     # 전체 UI + OCR API 호출 + 다운로드/복사 로직
│   ├── types.tsx                   # API 응답/내부 상태 타입 정의
│   ├── index.css                   # Tailwind + 디자인 토큰(@theme) + MDXEditor 커스텀 스타일
│   ├── components/
│   │   ├── ImageWithBoxes.tsx      # 원본 이미지 + OCR bbox 오버레이(SVG)
│   │   ├── MarkdownEditor.tsx      # MDXEditor 래퍼 (HTML 표 → GFM 표 변환 포함)
│   │   └── icons.tsx               # 디자인 아이콘 세트 (SVG)
│   └── assets/
├── public/
├── vite.config.ts
├── tsconfig*.json
└── eslint.config.js
```

## 알려진 제약

- OCR API 주소가 코드에 하드코딩되어 있어 배포 환경마다 소스 수정이 필요합니다.
- PDF 다중 페이지 합본 보기는 편집이 불가능합니다(개별 페이지 선택 시에만 편집 가능).
- 인증/권한 처리가 없습니다 — 현재는 로컬 OCR 서버와의 단순 연동만 가정합니다.
