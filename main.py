"""PDF 텍스트 파싱 + 기본 청킹 CLI.

사용법:
    python main.py <pdf_path> [--chunk-size 1000] [--chunk-overlap 200] [--out chunks.json]
"""
from __future__ import annotations

import argparse
import json

from rag.ingest import chunks_to_dicts, ingest_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF를 파싱하고 텍스트를 청크로 나눈다.")
    parser.add_argument("pdf_path", help="파싱할 PDF 파일 경로")
    parser.add_argument("--chunk-size", type=int, default=1000, help="청크 최대 문자 수 (기본 1000)")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="청크 간 겹침 문자 수 (기본 200)")
    parser.add_argument("--out", help="결과를 저장할 JSON 파일 경로 (미지정 시 표준출력에 요약 출력)")
    args = parser.parse_args()

    chunks = ingest_pdf(args.pdf_path, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    data = chunks_to_dicts(chunks)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"{len(data)}개 청크를 {args.out} 에 저장했습니다.")
    else:
        print(f"총 {len(data)}개 청크 생성됨.")
        for c in data[:3]:
            preview = c["text"][:80].replace("\n", " ")
            print(f"- [{c['id']}] p{c['page']} : {preview}...")


if __name__ == "__main__":
    main()
