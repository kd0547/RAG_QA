# deepagents 시제품 비교 (통합 지시서 F)

채택 여부를 정하기 위한 측정용이다. **운영 코드가 아니다.** 운영 가상환경(`.venv`)과 `requirements.txt`를 바꾸지 않는다.
결과와 해석은 [docs/dev_log/F-compare.md](../../../docs/dev_log/F-compare.md).

| 파일 | 내용 |
|------|------|
| `common.py` | 운영 DB·벡터DB를 작업 폴더에 복사하고 연결을 사본으로 돌린다. 로컬 모델·임베딩 주입, 평가 문항, 결과 기록 |
| `backend.py` | deepagents용 읽기 전용 가상 파일 backend. `/docs/<file_id>/p0003.md`를 읽으면 근거로 등록한다. `/skills/`는 저장소 절차 문서 |
| `run_compare.py` | 한 구성(`current` 또는 `proto`)으로 평가 문항을 돌려 `<작업 폴더>/<구성>.json`에 쓴다 |
| `compare.py` | 두 결과를 마크다운 표로 |

파일 이름이 `test_`로 시작하지 않아 `pytest tests`가 이 폴더를 실행하지 않는다 (운영 가상환경에는 deepagents가 없다).

## 실행

```
python -m venv .venv-deepagents
.venv-deepagents/Scripts/python.exe -m pip install -r requirements.txt deepagents

.venv/Scripts/python.exe tests/eval/deepagents_proto/run_compare.py current <작업 폴더>
.venv-deepagents/Scripts/python.exe tests/eval/deepagents_proto/run_compare.py proto <작업 폴더>
.venv/Scripts/python.exe tests/eval/deepagents_proto/compare.py <작업 폴더>
```

세 번째 인자로 문항 번호를 줄 수 있다 (예: `6` 또는 `1,5,6`). 로컬 모델 서버(`config.LLM_BASE_URL`)와 Ollama 임베딩이 필요하다. 메일은 보내지 않는다.

## 시제품 구성
- `create_deep_agent(model=로컬 모델, tools=현재 엔진의 도구(load_skill 제외), system_prompt=현재 엔진의 메일 실행과 같은 렌더링(v3), skills=["/skills/"], backend=읽기 전용 가상 backend)`
- 쓰기·셸·서브에이전트: 이 모델 키(`openai:<LLM_MODEL>`)에 `HarnessProfile(excluded_tools={write_file, edit_file, execute, task}, general_purpose_subagent=disabled)`을 등록하고, `FilesystemMiddleware(tools=["ls", "read_file", "glob", "grep"])`로 바꿔 끼운다. backend도 쓰기를 모두 거부한다
- 실행 한도: 현재 엔진과 같은 `ToolCallLimitMiddleware`(검색 6·도구 25)와 `ModelCallLimitMiddleware`(20)
