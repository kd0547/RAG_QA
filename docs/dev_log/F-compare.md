# F deepagents 시제품 비교

목적: 채택 여부를 정할 측정. **운영 코드에 넣지 않았다.** 어느 쪽이 낫다고 미리 정하지 않는다.
코드: [tests/eval/deepagents_proto/](../../tests/eval/deepagents_proto/README.md)

## 1. 설치 (별도 가상환경)

```
"C:\Users\…\Python312\python.exe" -m venv .venv-deepagents
.venv-deepagents/Scripts/python.exe -m pip install -q -r requirements.txt deepagents   → exit 0
```
- `.venv-deepagents/`를 `.gitignore`에 넣었다.
- `.venv`: 설치 전후 `pip freeze` 167줄이 같다. `requirements.txt`: 설치 전후 sha256이 같다.

| 패키지 | `.venv` (운영) | `.venv-deepagents` |
|--------|---------------|--------------------|
| deepagents | 없음 | **0.7.37** |
| langchain | 1.3.14 | 1.5.0 |
| langchain-core | 1.6.4 | 1.8.0 |
| langgraph | 1.2.9 | 1.2.21 |
| langgraph-prebuilt | 1.1.0 | 1.1.1 |
| langchain-openai | 1.6.3 | 1.7.4 |
| langchain-anthropic | 1.5.4 | 1.7.10 |
| langgraph-checkpoint / -sqlite | 4.3.1 / 3.1.3 | 4.3.1 / 3.1.3 |

`requirements.txt`가 버전을 고정하지 않아 새 가상환경에는 더 새 langchain·langgraph가 들어왔다. **deepagents를 채택하면 운영 langchain 1.3 → 1.5, langgraph 1.2.9 → 1.2.21 올림이 같이 따라온다.** 이번 측정의 시제품 쪽 숫자는 이 새 버전으로 잰 것이다.

## 2. 설치된 패키지에서 읽은 실제 API (0.7.37)

소스: `.venv-deepagents/Lib/site-packages/deepagents/` (`graph.py`, `backends/protocol.py`, `middleware/filesystem.py`, `middleware/skills.py`, `profiles/harness/harness_profiles.py`)

| 항목 | 실제 |
|------|------|
| 에이전트 생성 | `create_deep_agent(model, tools=None, *, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, …)` → LangGraph `CompiledStateGraph`. 내부는 langchain `create_agent` + 미들웨어 묶음 |
| 기본 도구 | `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`(파일), `execute`(셸, backend가 `SandboxBackendProtocol`일 때만 동작), `task`(서브에이전트). **계획 도구(write_todos)는 0.7.37 기본 묶음에 없다** |
| `tools=` | 더하기만 한다. 기본 도구를 빼지 못한다 |
| 기본 도구 빼기 | (a) 모델 키(`provider:model`)에 `HarnessProfile(excluded_tools=…)`을 `register_harness_profile`로 등록, (b) `FilesystemMiddleware(tools=[…])`를 `middleware=`로 넘겨 기본 것을 이름으로 갈아끼움 |
| 서브에이전트(`task`) 끄기 | 하네스 프로필의 `general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)` + `subagents=` 없음. `excluded_middleware`로는 `SubAgentMiddleware`를 뺄 수 없다(보호 대상) |
| 기본 미들웨어 | `FilesystemMiddleware` → (`SubAgentMiddleware`) → `SummarizationMiddleware`(deepagents 자체) → `PatchToolCallsMiddleware` → [사용자 미들웨어] → `SkillsMiddleware`(skills를 줄 때) → Anthropic·Bedrock·Fireworks 프롬프트 캐시(해당 모델에서만) → `MemoryMiddleware`(memory를 줄 때) → `UnsupportedContentMiddleware` → `ModelRefusalMiddleware` → `_ToolExclusionMiddleware` |
| backend 프로토콜 | `BackendProtocol`(추상 클래스): `ls`, `read(file_path, offset, limit) -> ReadResult`, `grep(pattern, path, glob, *, max_count)`(정규식이 아니라 글자 그대로), `glob`, `write`, `edit`, `delete`, `upload_files`, `download_files` (+ 각 async). 기본은 `StateBackend`(대화 상태 안의 가상 파일), 그 밖에 `FilesystemBackend`, `StoreBackend`, `CompositeBackend`, `LocalShellBackend`, 샌드박스 |
| skill 로딩 | `skills=["/skills/"]` → `SkillsMiddleware`가 backend의 `ls`로 하위 폴더를 찾고 `download_files`로 `SKILL.md`를 받아 YAML 머리말(`name`, `description`, 선택 `allowed-tools`)을 읽는다. 폴더 이름 = `name`. 시스템 프롬프트에 이름·설명 목록을 붙이고, 모델은 `read_file`로 본문을 읽는다 |
| 큰 도구 결과 | 20,000토큰(약 8만 자)을 넘는 도구 결과를 backend의 `/large_tool_results/`에 쓰고 요약으로 바꾼다. **쓰기가 실패하면 원래 결과를 그대로 둔다** (읽기 전용 backend에서는 이 기능이 사실상 꺼진다) |

## 3. 시제품 구성과 제한이 되었는지

| 요구 (지시서 F-3) | 한 것 | 됐는가 |
|-------------------|--------|--------|
| 같은 로컬 모델 | `agent.llm_provider`에 서버와 같은 `ChatOpenAI(config.LLM_MODEL, LLM_BASE_URL)` | 됨 |
| 같은 시스템 프롬프트 v3 | 두 구성 모두 사본 DB에 `ensure_v3()` 후 선택된 프롬프트를 현재 엔진의 메일 실행과 같은 `render_prompt`(별칭·상위 개념·서버 적용 절차 `mail-reply-style`·문서 그룹)로 렌더링. 선택 절차 목록은 시제품에서 deepagents가 붙인다 | 됨 (선택 절차 목록의 문구만 다르다) |
| 같은 도구 | 현재 엔진의 `active_tools()` 객체를 그대로 넘김 (근거 서비스·사양 서비스를 그대로 호출). `load_skill`만 뺐다 — 절차는 deepagents `skills=`로 읽힌다 | 됨 |
| 문서 읽기를 가상 파일 backend로, 읽기 전용, 읽을 때 근거 등록 | `RagReadOnlyBackend`: `/docs/INDEX.md`, `/docs/<file_id>/p0003.md`(file_page 검수본, 읽으면 `file_page` 근거 등록 + `read` 기록, 첫 줄에 근거 ID), `/skills/<name>/SKILL.md`. 쓰기·수정·삭제·업로드 거부 | 됨 |
| 쓰기·셸·서브에이전트·계획 도구 끄기 | 하네스 프로필 `excluded_tools={write_file, edit_file, execute, task}` + 일반 서브에이전트 끔 + `FilesystemMiddleware(tools=[ls, read_file, glob, grep])`. 계획 도구는 원래 없음 | 됨 — 실제 도구 노드의 도구 목록에 `write_file`·`edit_file`·`execute`·`task`가 없다 (아래 4절 목록) |
| 절차 문서는 `skills/`를 그대로 | 저장소 `SKILL.md` 원문을 그대로 돌려준다 (DB 승인 절차는 파일이 없어 머리말을 붙여 같은 형식). 메일 채널에서 모델이 고를 수 있는 절차만 (`certification-bundle`, `spec-compare`) | 됨 |
| 운영 DB를 쓰지 않음 | 두 구성 모두 작업 폴더의 `mail.db` 사본·`chroma` 사본·새 `agent_threads.db`. 운영 경로 연결을 사본으로 돌림 | 됨 (실행 전후 운영 `mail.db` 수정 시각 그대로) |
| 같은 실행 한도 | 시제품에도 `ToolCallLimitMiddleware`(검색 6·도구 25)와 `ModelCallLimitMiddleware`(20, end), `recursion_limit` 200 | 됨. 맥락 예산(24,000/40,000) 미들웨어는 시제품에 넣지 않았다 — deepagents 자체 요약 미들웨어가 그 자리다 (비교 대상) |

(4절 이후는 측정 결과)
