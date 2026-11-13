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

`requirements.txt`가 버전을 고정하지 않아 새 가상환경에는 더 새 langchain·langgraph가 들어왔다. **이번 시제품은 langchain 1.3.14 → 1.5.0, langgraph 1.2.9 → 1.2.21 변경도 함께 포함한다.** 따라서 아래 차이를 deepagents만의 효과로 분리할 수 없다. 모든 채택 방식에서 이 정확한 버전으로 올려야 한다는 뜻은 아니다.

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

## 4. 측정 결과 (2026-11-13)

현재 엔진과 시제품 실행은 모두 exit 0이다. 이미 완료된 실행의 `current.json`·`proto.json`을 읽고 `compare.py`로 표를 다시 생성했다. [기존 생성표](F-compare-table.md)와 줄바꿈을 제외한 내용이 같아 모델 실행을 반복하지 않았다.

**평가셋은 10칸이지만 실행 가능한 질문은 9개다.** 10번 「주간판매 질문 1건」은 기준선에 없어 `question`·`mail_uid`·`task_id`가 비어 있다. `common.cases()`가 질문과 `mail_uid`가 있는 항목만 골랐으며, 두 구성 모두 같은 1~9번을 실행했다. 10번을 통과나 실패에 넣지 않았다. [평가셋 설명](../../tests/eval/README.md)에 따라 담당자가 질문과 평가 기준을 채워야 한다.

### 4-1. 문항별 표

아래의 **통과는 서버의 근거 검증에서 errors가 없다는 뜻이며 정답률이 아니다.** `expected_evidence`·`expected_keywords`가 전 문항에서 비어 있어 정답 대조는 UNVERIFIED다. 인용한 근거 칸은 기존 생성기의 120자 제한 때문에 일부가 잘린다. 전체 인용 목록과 답변은 원본 JSON에 있다.

- 현재 엔진: {'deepagents': None, 'langchain': '1.3.14', 'langchain-core': '1.6.4', 'langgraph': '1.2.9', 'langchain-openai': '1.6.3'} · 프롬프트 `v3 근거 ID·사양` · 도구 14개
- 시제품: {'deepagents': '0.7.37', 'langchain': '1.5.0', 'langchain-core': '1.8.0', 'langgraph': '1.2.21', 'langchain-openai': '1.7.4'} · 프롬프트 `v3 근거 ID·사양` · 도구 17개 · 절차 ['certification-bundle', 'spec-compare']

| # | 문항 | 구성 | 답변 검증 | 인용한 근거 | 도구 호출(오류) | 모델 호출 | 입력/출력 토큰 | 초 |
|---|---|---|---|---|---|---|---|---|
| 1 | KC 인증서 요청 (그래프 경로) | 현재 | 통과 | KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107.pdf p1, KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107.pdf p4 | 8(0) | 6 | 72925/1742 | 23.0 |
|  |  | 시제품 | 통과 | KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107.pdf p1, KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107.pdf p3, KC인증서_안전확인_신고증명서_노트북_컴퓨터 | 7(0) | 6 | 78430/1414 | 18.8 |
| 2 | 인천공항 사전규격 대조 (첨부 PDF, 사양 비교) | 현재 | 통과 | 사양 DB: A650-GA70-PU02, 사양 DB: A650-GA70-OU01, _TG_NPC_제품제안서_A650_16인치_Jirisan_AMD_Kracken_RTX5070__Ver_1.0_20250415.docx | 16(1) | 10 | 201356/4965 | 66.6 |
|  |  | 시제품 | 통과 | 인천공항시설관리(주)_전산기기_사전규격(261016).pdf p5, 사양 DB: A650-GA70-PU02, 사양 DB: A650-GA70-OU01, 사양 DB: A650-GA70-PU02, 사양 DB: A650-G | 19(1) | 11 | 265560/4954 | 66.1 |
| 3 | 공군 입찰 규격 대조 (첨부 hwpx 1건) | 현재 | 통과 | 4.hwpx p1, _TG_NPC_제품제안서_A650_16인치_Jirisan_AMD_Kracken_RTX5070__Ver_1.0_20250415.docx p1, 사양 DB: A650-GA70-OU01, 사양 DB:  | 11(1) | 7 | 213560/15026 | 214.7 |
|  |  | 시제품 | 통과 (경고 1) | 없음 | 23(1) | 15 | 768540/9533 | 124.0 |
| 4 | LLM 추론 서버 입찰 (첨부 PDF 2건, 문서 밖 지식 필요) | 현재 | 통과 | 물품규격서_LLM추론시스템서버구매및설치수의계약안내공고_인천과학고등학교.pdf p2, 물품규격서_LLM추론시스템서버구매및설치수의계약안내공고_인천과학고등학교.pdf p3, 물품규격서_LLM추론시스템서버구매및설치수의계약안 | 11(0) | 7 | 108218/5782 | 88.2 |
|  |  | 시제품 | 통과 | 물품규격서_LLM추론시스템서버구매및설치수의계약안내공고_인천과학고등학교.pdf p1, 물품규격서_LLM추론시스템서버구매및설치수의계약안내공고_인천과학고등학교.pdf p2, 물품규격서_LLM추론시스템서버구매및설치수의계약안 | 13(1) | 9 | 152875/4914 | 79.0 |
| 5 | Essencore C910G 대체품 (SSD 시리즈 대표 1건, xlsx 49,933자) | 현재 | 통과 | 사양 DB: Essencore C910G 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Essencore C910G 1TB, 사양 D | 18(1) | 10 | 162689/5969 | 72.6 |
|  |  | 시제품 | 통과 | 사양 DB: Essencore C910G 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Essencore C910G 1TB, 사양 DB: Essencore C920 1TB, 사양 DB: | 16(1) | 10 | 181570/3391 | 44.0 |
| 6 | Ti600s ↔ C910G 대체 가능 여부 | 현재 | 통과 | 사양 DB: Essencore C910G 1TB | 17(1) | 10 | 106005/1637 | 24.5 |
|  |  | 시제품 | 통과 | 사양 DB: Essencore C910G 500GB, 사양 DB: Essencore C910G 1TB | 25(1) | 15 | 264882/2920 | 37.8 |
| 7 | 데스크탑 Sales Guide 요청 (문서 없음) | 현재 | 통과 | 없음 | 7(0) | 8 | 60645/555 | 7.2 |
|  |  | 시제품 | 통과 | 없음 | 6(0) | 5 | 49454/531 | 7.0 |
| 8 | RE: [응답] 인천공항… (회신, 인용문 포함) | 현재 | 통과 | _TG_NPC_제품제안서_A650_16인치_Jirisan_AMD_Kracken_RTX5070__Ver_1.0_20250415.docx p1, 사양 DB: A650-GA70-PU02, 사양 DB: A650-GA70-O | 23(1) | 13 | 241267/15177 | 180.1 |
|  |  | 시제품 | 통과 | _TG_NPC_제품제안서_A650_16인치_Jirisan_AMD_Kracken_RTX5070__Ver_1.0_20250415.docx p1, 사양 DB: A650, 사양 DB: A650, KC인증서_안전확인_신고증명 | 25(0) | 10 | 196694/9865 | 117.0 |
| 9 | RE: [테스트][검토]SSD (회신, 인용문 포함) | 현재 | 통과 | 사양 DB: Essencore C910G 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Essencore C910 500GB, 사양  | 26(1) | 15 | 290648/8598 | 107.1 |
|  |  | 시제품 | 통과 | 사양 DB: Essencore C910G 500GB, 사양 DB: Essencore C910 500GB, 사양 DB: Transcend MTE245S 500GB, 사양 DB: WD Black SN770 (채널) 50 | 22(0) | 14 | 298052/8427 | 101.6 |

| 구성 | 문항 | 검증 통과 | 도구 호출 합 | 도구 오류 합 | 입력 토큰 합 | 소요 합(초) |
|---|---|---|---|---|---|---|
| 현재 엔진 | 9 | 9 | 137 | 6 | 1,457,313 | 784.0 |
| deepagents 시제품 | 9 | 9 | 156 | 5 | 2,256,057 | 595.3 |

### 4-2. 추가 합계와 해석

| 지표 | 현재 엔진 | 시제품 | 시제품의 변화 |
|------|-----------|--------|---------------|
| 모델 호출 합 | 86 | 95 | +9회 |
| 출력 토큰 합 | 59,451 | 45,949 | -22.7% |
| 입력 토큰 합 | 1,457,313 | 2,256,057 | +54.8% |
| 도구 응답 메시지 합 | 137 | 156 | +13.9% |
| 소요 시간 합 | 784.0초 | 595.3초 | -24.1% |
| 경고 없는 서버 검증 통과 | 9/9 | 8/9 | 시제품 3번에 경고 1개 |

시제품은 8문항에서 더 빨랐고 6번에서는 느렸다. 총 188.7초 단축 중 90.7초는 3번, 63.1초는 8번에서 나왔다. 입력은 더 많이 쓰면서 출력은 줄었다. 1회씩 순차 실행한 결과여서 서버 부하·캐시·모델 출력 변동을 통제한 성능 우위로 읽을 수 없다.

`tool_calls`는 최종 메시지 목록의 `ToolMessage` 수이고, `model_calls`는 `AIMessage` 수다. 입력·출력 토큰도 그 목록의 `usage_metadata` 합이다 (`common.record`, `token_usage`). 요약으로 사라진 이전 메시지까지 누적하는 독립 호출 추적기는 아니다. `tool_errors`는 메시지의 error 상태와 본문 앞부분을 보는 휴리스틱 집계라 업무 판정 오류 수와 다르다. 현재 엔진 9번의 26회도 성공한 도구 실행 26회를 뜻하지 않는다. 제한·오류 응답이 포함될 수 있고, 결과 JSON에는 개별 도구 응답 본문이 없어 해당 1회 오류의 원인을 확정하지 않았다. 두 구성의 설정은 검색 6·도구 25·모델 20·recursion 200 그대로다.

### 4-3. 문항별 관찰

| 번호 | 관찰과 해석 |
|------|-------------|
| 1 KC 인증서 | 두 구성 모두 로컬에 있는 안전확인신고 문서를 인용하고 다른 인증 문서는 없다고 답했다. 현재 23.0초·8회, 시제품 18.8초·7회다. 시제품은 p1·p3·p4를 인용했다. 현재 답변은 p3의 제조공장 설명도 하지만 등록 인용은 p1·p4라, 근거 ID 검사만으로 문장별 사실 대조가 끝나지 않음을 보여 준다. |
| 2 인천공항 규격 | 둘 다 `compare_specs`를 1회 사용했다. 시간은 66.6/66.1초로 비슷하지만 시제품 입력은 201,356 → 265,560, 도구는 16 → 19회로 늘었다. 시제품은 첨부 사전규격 p5도 인용 목록에 남겼다. 요구조건과 옵션·최대 용량을 정확히 구분했는지는 별도 내용 검토가 필요하다. |
| 3 공군 규격 | 시제품은 214.7 → 124.0초로 빨라졌지만 입력은 213,560 → 768,540, 도구는 11 → 23회다. 첨부 읽기도 1 → 5회다. **시제품 답변은 제품 판정을 제시하면서 `근거 줄 없음` 경고와 인용 0건을 남겼다.** 읽은 근거가 있으면 근거 줄 누락을 warning으로만 처리하는 현재 `validate_answer` 규칙 때문에 ok=true다. 품질 향상으로 계산하지 않는다. |
| 4 LLM 서버 규격 | 두 구성은 첨부를 읽어 요구조건과 확인 필요 사항을 정리했다. 시제품은 88.2 → 79.0초지만 입력 108,218 → 152,875, 도구 11 → 13회다. 등록 목록에 없는 `read_skill` 호출명도 기록되어 도구 선택 오류가 관측된다. 엔진별 기능 충족 여부를 입증하는 제품 자료는 없어 정답 대조를 완료할 수 없다. |
| 5 C910G 대체품 | 둘 다 `get_specs`·`compare_specs`를 사용했다. 시제품은 72.6 → 44.0초, 도구 18 → 16회지만 입력은 늘었다. 시제품 본문은 C910G 1TB를 승인 상태까지 충족하는 후보로 소개하면서 표에는 `승인 중`으로 적어 표현이 일치하지 않는다. 서버 검증 통과를 제품 승인 판정의 정확성으로 해석하면 안 된다. |
| 6 TI600s ↔ C910G | 둘 다 TI600s 자료가 없어서 대체 여부를 판단하지 못했다. `compare_specs`를 부른 구성은 없다. 시제품은 24.5 → 37.8초, 도구 17 → 25회, 입력 106,005 → 264,882로 늘어 자료 부족 상황에서 검색이 더 길어졌다. 별도 스모크 28초·14회 결과 대신 이 표의 본 실행 수치를 쓴다. |
| 7 데스크탑 가이드 | 둘 다 해당 문서가 없다고 답했고 인용은 없다. 7.2/7.0초로 비슷하다. 시제품은 절차 파일도 읽지 않았다. 자료 없음 대응은 관측했지만 공식 정답 칸은 비어 있다. |
| 8 인천공항 회신 | 둘 다 현재 회신 본문에 포함된 인용문을 그대로 입력받고 `compare_specs`를 사용했다. 시제품은 180.1 → 117.0초, 입력 241,267 → 196,694다. 현재는 파생 모델별로, 시제품은 A650 중심으로 결과를 묶어 판정 범위가 다르다. 인용문 분리·이전 대화 자동 연결을 검증한 결과가 아니며, 파생 모델 판정의 정확성은 담당자 검토가 남는다. |
| 9 SSD 회신 | 둘 다 `compare_specs`를 2회 사용했다. 시제품은 107.1 → 101.6초, 도구 26 → 22회지만 입력은 290,648 → 298,052로 늘었다. 인용 근거 수도 17 → 12로 다르다. 수정 요청을 얼마나 충실히 반영했는지 정답 자료가 없어 시간·호출 수만으로 우열을 정하지 않는다. |

### 4-4. 도구 제한과 가상 파일 경로의 실제 사용

현재 도구 14개는 `graph_search`, `list_documents`, `grep_documents`, `read_pages`, `read_attachment`, `search_documents`, `rerank_documents`, `list_evidence`, `load_skill`, `list_spec_attributes`, `search_spec_items`, `get_specs`, `compare_specs`, `get_customer_history`다.

시제품은 여기서 `load_skill`을 빼고 `ls`, `read_file`, `glob`, `grep`를 더한 17개다. 결과 JSON의 실제 도구 노드 목록에 `write_file`, `edit_file`, `execute`, `task`, `write_todos`가 없다. **도구 선택지는 완전히 같지 않다.** 사양·근거 서비스 도구는 같은 객체를 재사용했고 절차 읽기와 파일 탐색 경로가 다르다.

시제품의 `virtual_files_read`는 1번에서 `/skills/certification-bundle/SKILL.md`, 2~6·8~9번에서 `/skills/spec-compare/SKILL.md`, 7번에서 빈 목록이다. **실제 9문항에서는 `/docs/` 가상 파일을 읽지 않았다.** 문서는 기존 `read_pages`·`read_attachment`로 읽었으므로 이번 수치로 가상 문서 backend의 효과나 그 경로의 근거 등록을 실증했다고 말할 수 없다. 3절의 backend 설명은 구현 확인이고, 실문항 사용 여부는 여기 기록과 구분한다.

## 5. 판단과 남은 검증

**이번 측정만으로 deepagents 채택을 결정하지 않는다.** 시제품 구성과 읽기 전용·도구 노출 제한은 구현됐고, 실행 가능한 같은 9문항의 측정도 끝났다. 속도는 줄었으나 입력 비용이 늘었고 근거 인용 누락이 1건 관측되어 일관된 개선으로 볼 수 없다.

- 로컬 등록 문서는 N5800 안전확인신고 증명서와 A650 제품제안서 **2개**다. 문의에 붙은 첨부와 사양 DB는 별도로 사용했다. 기준선의 17개 문서가 있는 개발 서버와 문서 검색 조건이 다르다.
- 현재 langchain 1.3.14/langgraph 1.2.9, 시제품 langchain 1.5.0/langgraph 1.2.21이다. 모델 설정과 v3 본문은 공유하지만 선택 절차 목록, 도구 목록, 맥락 관리도 다르다. 운영의 24,000/40,000 맥락 관리 대신 deepagents 자체 요약을 쓴 비교라는 점을 포함한다.
- 10번 주간판매 질문과 전 문항의 정답 칸을 담당자가 채워야 한다. 10문항 전체 완료로 보고하지 않는다.
- 개발 서버 17문서 기준선 재평가는 T6이고 아직 실행하지 않았다. 같은 문서·질문으로의 비교, 내용 검토, 필요시 반복 실행 후 채택을 판단한다. 운영 코드·한도·검증 규칙은 이 보고서 때문에 변경하지 않았다.

## 6. 재현 자료와 작업 기록

원본 폴더(저장소 밖 임시 경로, 평가 DB 사본 포함):

```text
C:\Users\김동욱\AppData\Local\Temp\claude\17b9a6af8eebcf5c\dfe462b8-3696-4fbb-be30-5a54662aefa0\scratchpad\f_run\
```

| 파일 | SHA-256 |
|------|---------|
| current.json | `fac2697f5163c802dfe6848d611f729525196a1ee873739d53430aa3276713b0` |
| proto.json | `5a0f4e473e1d87c35295e24f72674e3d5e6818923c2ef367e41fe17ce69c5223` |

```text
.venv/Scripts/python.exe tests/eval/deepagents_proto/compare.py <위 폴더>
exit 0 — F-compare-table.md와 동일 (18행 / 9문항)

done.txt:
current exit=0
proto exit=0

.venv/Scripts/python.exe -m pytest tests -q
453 passed in 65.63s (0:01:05)
```

원본 JSON과 평가 사본 폴더는 보존했다. 출력 마지막 전체 줄과 프론트 검증은 [T-T1](T-T1.md)에 기록한다. 이번 F1 마무리 변경 파일은 이 문서뿐이다. 시제품 코드·API 기록은 `ec846de`, 최초 생성표는 `7e6817b`, 결과 해석은 이 문서를 마무리한 커밋에 해당한다. 10문항 대신 9문항을 비교한 차이와 실증하지 못한 부분은 4~5절에 명시했다.
