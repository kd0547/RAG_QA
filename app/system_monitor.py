"""서버 자원(CPU·메모리·GPU) 측정.

백그라운드 스레드가 SAMPLE_SECONDS마다 측정해 최근 HISTORY_SIZE개를 메모리에 들고 있다(DB에는 남기지 않는다).
대시보드는 /monitor/system으로 현재 값과 최근 추이를 받는다.

- CPU·메모리: psutil. Docker 컨테이너 안에서도 /proc을 읽으므로 호스트(서버) 전체 사용량이 나온다.
- GPU: nvidia-smi. 컨테이너 안에서 쓰려면 docker-compose.yml에서 GPU(utility 기능)를 붙여야 한다.
  없으면 GPU 목록이 비고 gpu_error에 이유가 담긴다.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone

import psutil

logger = logging.getLogger(__name__)

SAMPLE_SECONDS = 5
HISTORY_SIZE = 360  # 5초 x 360 = 최근 30분

_GPU_FIELDS = (
    "index", "name", "utilization.gpu", "memory.used", "memory.total",
    "temperature.gpu", "power.draw", "power.limit",
)

_history: deque[dict] = deque(maxlen=HISTORY_SIZE)
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_gpu_error: str | None = None
_started_at = datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: str) -> float | None:
    value = value.strip()
    if not value or value.startswith("[") or value in ("N/A", "Not Supported"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_gpus() -> list[dict]:
    """nvidia-smi로 GPU별 사용률·VRAM·온도·전력을 읽는다. 실패하면 빈 목록과 _gpu_error."""
    global _gpu_error
    exe = shutil.which("nvidia-smi")
    if not exe:
        _gpu_error = "nvidia-smi를 찾을 수 없습니다 (NVIDIA 드라이버 또는 컨테이너 GPU 설정 확인)"
        return []
    try:
        result = subprocess.run(
            [exe, f"--query-gpu={','.join(_GPU_FIELDS)}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _gpu_error = f"nvidia-smi 실행 실패: {exc}"
        return []
    if result.returncode != 0:
        _gpu_error = f"nvidia-smi 오류: {(result.stderr or result.stdout).strip()[:200]}"
        return []

    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(_GPU_FIELDS):
            continue
        mem_used, mem_total = _num(parts[3]), _num(parts[4])
        gpus.append({
            "index": int(_num(parts[0]) or 0),
            "name": parts[1],
            "util_percent": _num(parts[2]),
            "mem_used_mb": mem_used,
            "mem_total_mb": mem_total,
            "mem_percent": round(mem_used / mem_total * 100, 1) if mem_used is not None and mem_total else None,
            "temperature_c": _num(parts[5]),
            "power_w": _num(parts[6]),
            "power_limit_w": _num(parts[7]),
        })
    _gpu_error = None
    return gpus


def _sample() -> dict:
    mem = psutil.virtual_memory()
    # used는 OS마다 계산이 달라서, 실제로 더 쓸 수 있는 양(available)을 뺀 값을 사용량으로 본다
    mem_used = mem.total - mem.available
    try:
        load = [round(v, 2) for v in psutil.getloadavg()]
    except (AttributeError, OSError):
        load = None
    return {
        "ts": _now_iso(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "load_avg": load,
        "mem_used": mem_used,
        "mem_total": mem.total,
        "mem_percent": round(mem_used / mem.total * 100, 1) if mem.total else None,
        "gpus": _read_gpus(),
    }


def _loop() -> None:
    psutil.cpu_percent(interval=None)  # 첫 호출은 기준점만 잡고 0을 돌려준다
    while not _stop.wait(SAMPLE_SECONDS if _history else 1):
        try:
            sample = _sample()
            with _lock:
                _history.append(sample)
        except Exception:
            logger.exception("서버 자원 측정 실패")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="system-monitor", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=SAMPLE_SECONDS + 1)


def snapshot() -> dict:
    """현재 값(가장 최근 측정)과 최근 추이, 서버 기본 정보."""
    with _lock:
        history = list(_history)
    current = history[-1] if history else _sample()  # 스레드가 아직 한 번도 안 돌았으면 바로 잰다
    return {
        "host": {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "in_container": os.path.exists("/.dockerenv"),
            "cpu_count": psutil.cpu_count(logical=True),
            "cpu_physical": psutil.cpu_count(logical=False),
            "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "app_started_at": _started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "interval_seconds": SAMPLE_SECONDS,
        "current": current,
        "gpu_error": _gpu_error,
        # 추이 그래프에 필요한 값만 줄여서 보낸다
        "history": [
            {
                "ts": s["ts"],
                "cpu": s["cpu_percent"],
                "mem": s["mem_percent"],
                "gpus": [{"util": g["util_percent"], "mem": g["mem_percent"]} for g in s["gpus"]],
            }
            for s in history
        ],
    }
