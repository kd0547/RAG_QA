"""설치된 PaddleOCR-VL 환경을 재사용하는 로컬 OCR.

앱의 torch/LangChain 환경과 Paddle 환경을 별도 프로세스로 격리한다.
한 프로세스에서 모델을 한 번만 로드하고 요청은 순차 처리한다.
이 파일의 --worker 모드는 Paddle 환경에서 실행되므로 표준 라이브러리만
최상위에서 import한다. 설정/모델은 각 프로세스에서 필요할 때 불러온다.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading

# 직접 실행하는 worker에는 프로젝트 패키지 의존성이 필요 없다.
if __name__ != "__main__":
    from ocr.base import OCRBackend
else:
    OCRBackend = object


class VLMOCR(OCRBackend):
    name = "vlm"

    def __init__(self):
        import config

        self.python = Path(config.PADDLEOCR_PYTHON).expanduser().resolve()
        self.cache_dir = Path(config.PADDLEOCR_CACHE_DIR).resolve()
        self.timeout = config.PADDLEOCR_TIMEOUT
        self.settings = {
            "vl_rec_model_dir": str(Path(config.PADDLEOCR_VL_MODEL_DIR).resolve()),
            "layout_detection_model_dir": str(Path(config.PADDLEOCR_LAYOUT_MODEL_DIR).resolve()),
            "device": config.PADDLEOCR_DEVICE,
        }
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("PADDLEOCR_TIMEOUT은 0보다 큰 유한한 값이어야 합니다.")
        self._process = None
        self._responses = None
        self._lock = threading.RLock()

    def _start(self):
        if self._process is not None and self._process.poll() is None:
            return
        self.close()
        if not self.python.is_file():
            raise FileNotFoundError(f"PADDLEOCR_PYTHON을 확인하세요: {self.python}")
        for key in ("vl_rec_model_dir", "layout_detection_model_dir"):
            if not Path(self.settings[key]).is_dir():
                raise FileNotFoundError(f"PaddleOCR 모델 폴더가 없습니다 ({key}): {self.settings[key]}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # 부모 앱의 패키지 검색 경로가 별도 가상환경을 오염시키지 않게 한다.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.update(
            PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
            PYTHONDONTWRITEBYTECODE="1",
            PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",
            PADDLE_PDX_CACHE_HOME=str(self.cache_dir / "paddlex"),
            HF_HOME=str(self.cache_dir / "huggingface"),
            MPLCONFIGDIR=str(self.cache_dir / "matplotlib"),
            TEMP=str(self.cache_dir), TMP=str(self.cache_dir),
        )
        self.log_path = self.cache_dir / f"worker-{os.getpid()}.log"
        with self.log_path.open("ab") as log:
            self._process = subprocess.Popen(
                [str(self.python), "-u", str(Path(__file__).resolve()), "--worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                text=True, encoding="utf-8", env=env, cwd=str(self.cache_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        responses = queue.Queue()
        self._responses = responses
        stream = self._process.stdout

        def read_responses():
            try:
                for line in stream:
                    responses.put(line)
            finally:
                responses.put(None)

        threading.Thread(target=read_responses, daemon=True).start()

    def ocr_image(self, image_bytes: bytes) -> str:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("OCR 입력은 비어 있지 않은 이미지 bytes여야 합니다.")
        with self._lock:
            self._start()
            # 짧은 경로만 pipe로 보내 큰 이미지 쓰기로 timeout 이전에 막히는 것을 방지.
            with tempfile.TemporaryDirectory(prefix="request-", dir=self.cache_dir) as tmp:
                image_path = Path(tmp) / "input.img"
                image_path.write_bytes(image_bytes)
                request = {"image_path": str(image_path), "settings": self.settings}
                try:
                    self._process.stdin.write(json.dumps(request) + "\n")
                    self._process.stdin.flush()
                    line = self._responses.get(timeout=self.timeout)
                    if line is None:
                        raise RuntimeError(f"PaddleOCR 프로세스가 종료되었습니다. 로그: {self.log_path}")
                    response = json.loads(line)
                    if "error" in response:
                        raise RuntimeError(f"PaddleOCR 실패: {response['error']} (로그: {self.log_path})")
                    text = response["text"]
                    if not isinstance(text, str):
                        raise TypeError("PaddleOCR 응답이 문자열이 아닙니다.")
                    return _normalize_markdown(text)
                except queue.Empty as exc:
                    self.close()
                    raise TimeoutError(f"PaddleOCR 제한 시간 {self.timeout}초 초과. 로그: {self.log_path}") from exc
                except BaseException:
                    # 오류/중단 후 남은 응답을 다음 요청의 결과로 사용하지 않는다.
                    self.close()
                    raise

    def close(self):
        with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            if process.poll() is None:
                if os.name == "nt":
                    # Windows venv launcher가 만든 실제 Python 자식도 함께 종료.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                if process.poll() is None:
                    process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def ocr_image(image_bytes: bytes) -> str:
    """PaddleOCR를 명시적으로 호출할 때 사용하는 호환 함수."""
    from ocr.provider import get_ocr_backend
    return get_ocr_backend("vlm").ocr_image(image_bytes)


def _normalize_markdown(text: str) -> str:
    """HTML 표의 병합 셀을 빈 칸으로 펼쳐 기존 RAG/표 가져오기와 호환한다."""
    from bs4 import BeautifulSoup

    def convert_table(match):
        soup = BeautifulSoup(match.group(), "html.parser")
        occupied = set()
        rows = []
        for row_index, tr in enumerate(soup.find_all("tr")):
            row, column = {}, 0
            for cell in tr.find_all(["th", "td"], recursive=False):
                while (row_index, column) in occupied:
                    column += 1
                for br in cell.find_all("br"):
                    br.replace_with("\n")
                value = cell.get_text(" ", strip=True).replace("|", r"\|").replace("\n", "<br>")
                row[column] = value
                try:
                    rowspan = min(1000, max(1, int(cell.get("rowspan", 1))))
                    colspan = min(1000, max(1, int(cell.get("colspan", 1))))
                except (TypeError, ValueError):
                    rowspan = colspan = 1
                for r in range(row_index, row_index + rowspan):
                    for c in range(column, column + colspan):
                        occupied.add((r, c))
                column += colspan
            rows.append(row)
        if not rows or not occupied:
            return match.group()
        width = max(c for _, c in occupied) + 1
        lines = ["| " + " | ".join(row.get(c, "") for c in range(width)) + " |" for row in rows]
        lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
        return "\n\n" + "\n".join(lines) + "\n\n"

    text = re.sub(r"<table\b[^>]*>.*?</table>", convert_table, text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _worker():
    # Python/C++ 라이브러리의 stdout 로그도 JSON 응답 채널과 분리한다.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    pipeline = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            import numpy as np
            from PIL import Image, ImageOps

            with Image.open(request["image_path"]) as img:
                img = ImageOps.exif_transpose(img).convert("RGBA")
                background = Image.new("RGBA", img.size, "white")
                rgb = Image.alpha_composite(background, img).convert("RGB")
                # PaddleX의 ndarray 입력은 OpenCV BGR 순서.
                pixels = np.asarray(rgb)[:, :, ::-1].copy()
            if pipeline is None:
                from paddleocr import PaddleOCRVL
                pipeline = PaddleOCRVL(
                    pipeline_version="v1.6", **request["settings"],
                    use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_queues=False, use_ocr_for_image_block=False,
                    markdown_ignore_labels=[],
                )
            results = pipeline.predict(pixels)
            if not results:
                raise RuntimeError("PaddleOCR가 페이지 결과를 반환하지 않았습니다.")
            texts = []
            for result in results:
                markdown = result.markdown
                text = markdown["markdown_texts"]
                # RAG에 base64나 저장되지 않은 crop 경로를 넣지 않는다.
                # 이미지/로고/코드는 설명을 생성하지 않고 위치만 표시한다.
                text = re.sub(r"<img\b[^>]*>", "[이미지]", text, flags=re.IGNORECASE)
                text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[이미지]", text)
                texts.append(text)
            response = {"text": "\n\n".join(texts).strip()}
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            response = {"error": f"{type(exc).__name__}: {exc}"}
        protocol.write(json.dumps(response, ensure_ascii=False) + "\n")
        protocol.flush()


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("앱에서는 ocr.provider.ocr_image를 사용하세요.")
    _worker()
