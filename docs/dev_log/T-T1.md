# T1 자동 테스트 재확인과 확인용 서버 정리

확인일: 2026-11-13. 대상: [통합 지시서 9절](../opus_development_instructions_remaining.md), [인수인계](HANDOFF-remaining.md).

## 결과

| 검사 | 결과 |
|------|------|
| 전체 pytest | **453 passed**, exit 0 |
| 프론트 TypeScript | 통과, exit 0 |
| 전체 `eslint src` | **실패: 기존 App.tsx 오류 2건·경고 1건**, exit 1 |
| 변경 폴더 `eslint src/spec src/mail src/knowledge` | 통과, exit 0 |
| 프론트 임시 폴더 빌드 | 통과, exit 0. 큰 번들 경고 있음 |

T1의 검사를 실행하고 기록했지만, 전체 린트가 실패하므로 **T1의 모든 통과 조건을 충족한 것은 아니다.** 인수인계에서 이미 분리해 둔 기존 오류로 사용자에게 보고한다. 이번 마무리에서는 운영 코드와 App.tsx를 수정하지 않았다.

## 명령과 실제 출력

저장소 루트에서:

```text
.venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 79%]
........................................................................ [ 95%]
.....................                                                    [100%]
453 passed in 65.63s (0:01:05)
```

출력이 20줄보다 짧아 전체를 기록했다. `tests/conftest.py`가 운영 `mail.db`·`agent_threads.db` 연결을 세션 임시 DB로 바꾸고 벡터 저장소와 모델을 대역으로 격리한다.

`frontend`에서:

```text
npx --no-install tsc -b
(출력 없음, exit 0)

npx --no-install eslint src/spec src/mail src/knowledge
(출력 없음, exit 0)

npx --no-install eslint src
(exit 1, 아래는 오류 위치 요약)
src/App.tsx
315:36 error   react-hooks/immutability — Cannot access variable before it is declared (runOcr)
316:8  warning react-hooks/exhaustive-deps — useCallback dependency runOcr 누락
319:32 error   react-hooks/preserve-manual-memoization — Existing memoization could not be preserved
✖ 3 problems (2 errors, 1 warning)
```

`App.tsx`의 마지막 변경은 `52963dd`(2026-11-05)다. 통합 지시서 구현 시작 전 `1d8b4d5`부터 현재까지 이 파일에 변경이 없다. 전체 린트의 마지막 20줄은 다음과 같다.

```text
C:\TG_AI_DEV\rag_QA\frontend\src\App.tsx:319:32
  317 |
  318 |     // ===== OCR 호출 =====
> 319 |     const runOcr = useCallback(async (item: OcrFile): Promise<void> => {
      |                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> 320 |         setFiles((prev) =>
      | ^^^^^^^^^^^^^^^^^^^^^^^^^^
> 321 |             prev.map((f) =>
      …
      | ^^^^^^^^^^^^^^^^^^^^^^^^^^
> 369 |         }
      | ^^^^^^^^^^^^^^^^^^^^^^^^^^
> 370 |     }, []);
      | ^^^^^^ Could not preserve existing memoization
  371 |
  372 |     // ===== 이벤트 핸들러 =====
  373 |     const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {                                                                                                                                                                                                                                                                                             react-hooks/preserve-manual-memoization

✖ 3 problems (2 errors, 1 warning)

```

빌드는 지시서 T3의 운영 반영과 구분하여 임시 출력 폴더를 사용했다.

```powershell
npm run build -- --outDir "$env:TEMP\ragqa-remaining-build"
```

빌드 출력 마지막 20줄:

```text
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-B20Gfwut.js               30.69 kB │ gzip:  12.73 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-aGiWA1JB.js               34.13 kB │ gzip:  13.02 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/sql-Co0THMfV.js                36.85 kB │ gzip:  10.90 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-oimK29FW.js               40.71 kB │ gzip:  16.95 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-DpXDAogg.js               43.67 kB │ gzip:  15.06 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-CVO5BbGO.js               44.57 kB │ gzip:  19.33 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-CINDySZw.js               70.80 kB │ gzip:  26.11 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-gfk-uWSQ.js               84.58 kB │ gzip:  33.74 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-DRjLFe_2.js               97.74 kB │ gzip:  28.65 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/dist-Bm6THcK6.js              103.90 kB │ gzip:  34.77 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/App-CJ2oUU5p.js               303.71 kB │ gzip:  92.40 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/index-CrHnCQ-Z.js             892.78 kB │ gzip: 259.47 kB
../../../Users/김동욱/AppData/Local/Temp/ragqa-remaining-build/assets/MarkdownEditor-BC_aRRGr.js  1,022.72 kB │ gzip: 329.32 kB

✓ built in 453ms
[plugin builtin:vite-reporter]
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
```

운영 `frontend/dist`는 이 명령의 출력 대상이 아니다. 프로젝트 밖 outDir을 자동 비우지 않는다는 경고와 500 kB 초과 청크 경고가 있었고 빌드는 exit 0으로 끝났다.

샌드박스에서는 사용자 설치 Python 실행과 사용자 npm 경로 접근이 실패하여, 같은 명령을 승인된 권한으로 다시 실행했다. 패키지 설치·업데이트는 하지 않았다. 원시 로그는 실행 사용자 `%TEMP%/ragqa-remaining-{pytest,tsc,eslint,eslint-changed,build}.log`에 남겼다.

## 확인용 서버·사본 정리

- 인수인계에 지정된 8010·5174 포트에는 LISTEN 연결이 없었다. `stub_backend.py`, `skill_stub.py`, 5174 인자를 가진 Python·Node·cmd 프로세스도 없어 종료할 대상은 없었다.
- 아래 두 경로를 절대 경로로 확인했다. 사용자 Temp의 바로 아래 `ragqa-stub-*` 디렉터리이고 링크가 아니며, 내부에는 각각 `mail.db` 사본 하나만 있었다. 두 디렉터리만 삭제했다.

```text
C:\Users\김동욱\AppData\Local\Temp\ragqa-stub-ebpja3pn
C:\Users\김동욱\AppData\Local\Temp\ragqa-stub-hbtt__fw
```

F 비교의 `f_run` 원본 결과와 사본 DB는 위 삭제 대상에 포함하지 않았다. `.claude/launch.json`은 기존 실행 설정으로 그대로 두었다.

## 변경 파일·확인하지 않은 것

이 항목의 저장소 변경은 본 기록 파일뿐이다. 테스트 뒤에 문서만 수정하므로 같은 전체 테스트 출력을 F1·T1·Z2 마무리의 공통 검증으로 사용한다. 운영 DB 마이그레이션 예행은 완료된 [T-migration](T-migration.md)을 참조하며 재실행하지 않았다.

T3 운영 백업·빌드·재시작, T4 실서버·실모델 확인, T5 Gemini 검증, T6 개발 서버 기준선 비교는 이번 실행에 포함하지 않았다. 이후 조건과 담당자는 [R-summary](R-summary.md)에 정리한다.

커밋: 이 문서를 추가한 T1 기록 커밋 (`git log -1 -- docs/dev_log/T-T1.md`).
