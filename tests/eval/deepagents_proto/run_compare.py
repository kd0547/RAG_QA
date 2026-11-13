"""평가 문항을 한 구성으로 돌려 결과를 JSON으로 쓴다 (통합 지시서 F-4). 운영 코드가 아니다.

    # 현재 엔진 (운영 가상환경)
    .venv/Scripts/python.exe tests/eval/deepagents_proto/run_compare.py current <작업 폴더>
    # deepagents 시제품 (별도 가상환경)
    .venv-deepagents/Scripts/python.exe tests/eval/deepagents_proto/run_compare.py proto <작업 폴더>

두 구성 모두 같은 로컬 모델, 같은 시스템 프롬프트 v3, 같은 근거·사양 서비스와 같은 운영 DB 사본에서 시작한다
(구성마다 작업 폴더 안에 따로 사본을 만든다). 메일은 보내지 않는다. 결과: <작업 폴더>/<구성>.json
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402


def run_current(case: dict, question: str, attachments: list) -> dict:
    from agent import agent as agent_module
    from agent.evidence_context import Owner

    captured: dict = {}
    original_finish = agent_module._finish_answer

    def finish(result, owner):
        captured["messages"] = result["messages"]
        return original_finish(result, owner)

    agent_module._finish_answer = finish
    started = time.perf_counter()
    try:
        out = agent_module.run_agent_temp_attachments(
            question, mode="local", attachments=attachments, owner=Owner("task", case["task_id"]),
            thread_id=f"eval-current:{uuid4().hex}",
        )
        return common.record(case, answer=out["answer"], validation=out["validation"], sources=out["sources"],
                             messages=captured.get("messages", []), started=started)
    except Exception as exc:  # 실패도 결과로 남긴다
        return common.record(case, answer=None, validation=None, sources=[], messages=captured.get("messages", []),
                             started=started, error=f"{type(exc).__name__}: {exc}")
    finally:
        agent_module._finish_answer = original_finish


def build_proto():
    """deepagents 에이전트: 같은 모델·도구·프롬프트, 읽기 전용 가상 파일, 쓰기·셸·서브에이전트 끔."""
    from deepagents import (
        FilesystemMiddleware, GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile,
    )
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware

    import config
    from agent import agent as agent_module
    from agent import skills
    from agent.llm_provider import get_llm_model
    from backend import RagReadOnlyBackend

    model = get_llm_model("local")
    # 이 모델에만 적용: 쓰기·셸·서브에이전트(task) 도구를 모델에 보이지 않게, 일반 서브에이전트를 만들지 않게
    register_harness_profile(f"openai:{config.LLM_MODEL}", HarnessProfile(
        excluded_tools=frozenset({"write_file", "edit_file", "execute", "task"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ))
    optional = [s.name for s in skills.selectable_skills("mail")]
    backend = RagReadOnlyBackend(optional)
    # 절차는 deepagents 방식(skills=)으로 읽힌다. 현재 엔진의 load_skill은 빼고 나머지 도구는 같은 객체를 쓴다
    tools = [t for t in agent_module.active_tools() if t.name != "load_skill"]
    middleware = [
        FilesystemMiddleware(backend=backend, tools=["ls", "read_file", "glob", "grep"]),
        # 현재 엔진과 같은 실행 한도
        ToolCallLimitMiddleware(tool_name="search_documents", run_limit=agent_module.SEARCH_CALLS_PER_RUN),
        ToolCallLimitMiddleware(run_limit=agent_module.TOOL_CALLS_PER_RUN),
        ModelCallLimitMiddleware(run_limit=agent_module.MODEL_CALLS_PER_RUN, exit_behavior="end"),
    ]
    import repository
    from agent.prompt import render_prompt

    # 현재 엔진의 메일 실행과 같은 시스템 프롬프트 (v3 + 별칭 + 상위 개념 + 서버 적용 절차 + 문서 그룹). 선택 절차 목록은
    # deepagents의 SkillsMiddleware가 붙인다
    system = render_prompt(
        repository.prompt_repo.get_system_prompt(), agent_module.ALIASES, repository.group_repo.list_all(),
        agent_module._graph_concepts(), applied_skills=skills.applied_skills("mail", rejecting=False), optional_skills=None,
    )
    agent = create_deep_agent(model=model, tools=tools, system_prompt=system, middleware=middleware,
                              skills=["/skills/"], backend=backend)
    return agent, backend, optional


def run_proto(agent, backend, case: dict, question: str, attachments: list) -> dict:
    import repository
    from langchain_core.messages import HumanMessage

    import config
    from agent import agent as agent_module
    from agent import skills
    from agent.evidence_context import Owner, owner_scope, run_scope
    from agent.validation import validate_answer

    owner = Owner("task", case["task_id"])
    started = time.perf_counter()
    messages: list = []
    with owner_scope(owner):
        applied = skills.applied_skills("mail", rejecting=False)
        run_id = repository.evidence_repo.start_run(owner.type, owner.id, config.LLM_MODEL, None,
                                                    label="deepagents 시제품", skills=[s.ref() for s in applied])
        preread: list[str] = []
        content: list[dict] = [{"type": "text", "text": question}]
        for index, attachment in enumerate(attachments, start=1):
            content.extend(agent_module._attachment_to_blocks(attachment, index, preread))
        hint = agent_module.customer_history_hint(owner)
        if hint:
            content.append({"type": "text", "text": hint})
        for evidence_id in preread:
            repository.evidence_repo.record_use(run_id, evidence_id, "read")
        try:
            with run_scope(run_id):
                result = agent.invoke(
                    {"messages": [HumanMessage(content=content)]},
                    config={"recursion_limit": agent_module.RECURSION_LIMIT,
                            "configurable": {"thread_id": f"eval-proto:{uuid4().hex}"}},
                )
            messages = result["messages"]
            final = messages[-1] if messages else None
            answer = agent_module.answer_text(final).strip() if getattr(final, "type", None) == "ai" else ""
            if not answer or answer.startswith(agent_module.MODEL_LIMIT_MESSAGE_PREFIX):
                repository.evidence_repo.finish_run(run_id, "limit" if answer else "error", [], None, None, answer or "빈 답변")
                return common.record(case, answer=answer or None, validation=None, sources=[], messages=messages,
                                     started=started, error=answer or "빈 답변")
            tokens_in, tokens_out = common.token_usage(messages)
            repository.evidence_repo.finish_run(run_id, "ok", [], tokens_in, tokens_out)
            validation = validate_answer(run_id, owner, answer)
            sources = agent_module.evidence_sources(run_id, owner)
            out = common.record(case, answer=validation.answer, validation=validation.to_dict(), sources=sources,
                                messages=messages, started=started)
            out["virtual_files_read"] = list(backend.reads)
            return out
        except Exception as exc:
            repository.evidence_repo.finish_run(run_id, "error", [], None, None, f"{type(exc).__name__}: {exc}")
            return common.record(case, answer=None, validation=None, sources=[], messages=messages, started=started,
                                 error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
        finally:
            backend.reads.clear()


def main() -> int:
    kind, work = sys.argv[1], Path(sys.argv[2]) / sys.argv[1]
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    paths = common.setup(work)
    common.load_models()
    import repository
    from agent import agent as agent_module
    from agent import skills

    skills.reload_skills()
    repository.prompt_repo.ensure_default()
    repository.prompt_repo.ensure_v2()
    repository.prompt_repo.ensure_v3()   # 두 구성 모두 v3로
    results = {"kind": kind, "db_copy": str(paths["db"]), "prompt": repository.prompt_repo.get_selected().name,
               "versions": versions(), "cases": []}
    if kind == "current":
        agent_module.set_checkpointer(agent_module.open_checkpointer(paths["threads"]))
        results["tools"] = [t.name for t in agent_module.active_tools()]
    else:
        proto, backend, optional = build_proto()
        results["tools"] = sorted(proto.nodes["tools"].bound.tools_by_name)
        results["skills_offered"] = optional
    for index, case in enumerate(common.cases(), start=1):
        if only and str(index) not in only:
            continue
        question, attachments = common.mail_input(case)
        if question is None:
            results["cases"].append({"eval_title": case["eval_title"], "error": "사본 DB에 메일 없음"})
            continue
        print(f"[{kind}] {index}. {case['eval_title']}", flush=True)
        if kind == "current":
            out = run_current(case, question, attachments)
        else:
            out = run_proto(proto, backend, case, question, attachments)
        print(f"    -> {out['seconds']}초, 도구 {out['tool_calls']}회(오류 {out['tool_errors']}), "
              f"검증 {None if not out.get('validation') else out['validation']['ok']}, 오류 {out['error'] and out['error'][:120]}", flush=True)
        results["cases"].append(out)
        (work.parent / f"{kind}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    found = {}
    for name in ("deepagents", "langchain", "langchain-core", "langgraph", "langchain-openai"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = None
    return found


if __name__ == "__main__":
    raise SystemExit(main())
