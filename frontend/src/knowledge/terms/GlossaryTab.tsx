import { useCallback, useEffect, useState } from 'react';
import { btnGhost, btnPrimary, errorMessage, inputCls } from '../../spec/styles';
import { ListItem, Notice, Pill } from '../../spec/ui';
import { termApi, type ResolvedTerm, type Term, type TermTargets } from './api';
import { TermEditor } from './TermEditor';
import { TermImport } from './TermImport';

type Mode = { kind: 'none' } | { kind: 'new' } | { kind: 'edit'; id: number } | { kind: 'import' };

/**
 * 용어집 탭 (/knowledge?tab=terms).
 * 왼쪽: 용어 목록·검색, [직접 추가] [엑셀 가져오기]. 오른쪽: 고른 작업(수정·추가·가져오기) 또는 질문 해석 미리보기.
 * 용어집은 그래프에 쓰지 않는다. 그래프 검색이 질문을 읽을 때만 쓴다.
 */
export function GlossaryTab() {
    const [terms, setTerms] = useState<Term[] | null>(null);
    const [targets, setTargets] = useState<TermTargets | null>(null);
    const [filter, setFilter] = useState('');
    const [mode, setMode] = useState<Mode>({ kind: 'none' });
    const [notice, setNotice] = useState('');
    const [loadError, setLoadError] = useState('');

    const reload = useCallback(async () => {
        try {
            setTerms(await termApi.list());
            setLoadError('');
        } catch (e) {
            setLoadError(errorMessage(e, '용어집을 불러오지 못했습니다. 백엔드가 최신 코드로 떠 있는지 확인하세요 (재시작 필요).'));
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        Promise.all([termApi.list(), termApi.targets()])
            .then(([list, t]) => {
                if (cancelled) return;
                setTerms(list);
                setTargets(t);
            })
            .catch((e) => { if (!cancelled) setLoadError(errorMessage(e, '용어집을 불러오지 못했습니다. 백엔드가 최신 코드로 떠 있는지 확인하세요 (재시작 필요).')); });
        return () => { cancelled = true; };
    }, []);

    const selected = mode.kind === 'edit' ? terms?.find((t) => t.id === mode.id) ?? null : null;
    const shown = (terms ?? []).filter((t) => {
        const q = filter.trim().toLowerCase();
        if (!q) return true;
        return [t.name, ...t.aliases, t.description].some((v) => v.toLowerCase().includes(q));
    });

    function open(next: Mode) {
        setMode(next);
        setNotice('');
    }

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-80 shrink-0 border-b md:border-b-0 md:border-r border-divide flex flex-col min-h-0">
                <div className="p-3 space-y-2 border-b border-divide">
                    <div className="flex gap-2">
                        <button type="button" className={`${btnPrimary} flex-1 justify-center`} onClick={() => open({ kind: 'new' })}>직접 추가</button>
                        <button type="button" className={`${btnGhost} flex-1 justify-center`} onClick={() => open({ kind: 'import' })}>엑셀 가져오기</button>
                    </div>
                    <input className={inputCls} placeholder="용어·표기 찾기" aria-label="용어 찾기" value={filter} onChange={(e) => setFilter(e.target.value)} />
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-0.5">
                    {terms === null && !loadError && <p className="p-3 text-[12px] text-muted">불러오는 중…</p>}
                    {terms !== null && terms.length === 0 && (
                        <p className="p-3 text-[12px] leading-relaxed text-muted">아직 등록된 용어가 없습니다. 직접 추가하거나 엑셀 양식을 받아 채운 뒤 가져오세요.</p>
                    )}
                    {terms !== null && terms.length > 0 && shown.length === 0 && <p className="p-3 text-[12px] text-muted">맞는 용어가 없습니다.</p>}
                    {shown.map((t) => (
                        <ListItem
                            key={t.id}
                            active={mode.kind === 'edit' && mode.id === t.id}
                            title={t.name}
                            subtitle={t.kind === 'bundle'
                                ? `구성: ${t.members.map((m) => m.name).join(' + ')}`
                                : t.aliases.length ? t.aliases.join(', ') : '다른 표기 없음'}
                            badge={t.kind === 'bundle'
                                ? <Pill tone="brand">묶음</Pill>
                                : t.target_text ? <Pill>{t.target_label || t.target_key}</Pill> : undefined}
                            onClick={() => open({ kind: 'edit', id: t.id })}
                        />
                    ))}
                </div>
                {terms !== null && <p className="px-3 py-2 border-t border-divide text-[11px] text-muted">용어 {terms.length}개</p>}
            </aside>

            <main className="flex-1 min-w-0 min-h-0 overflow-y-auto p-5 md:p-6">
                {loadError && <div className="mb-4"><Notice kind="error">{loadError}</Notice></div>}
                {notice && <div className="mb-4"><Notice kind="ok">{notice}</Notice></div>}

                {mode.kind === 'new' && (
                    <TermEditor key="new" term={null} terms={terms ?? []} targets={targets}
                        onSaved={(t) => { void reload(); setMode({ kind: 'edit', id: t.id }); setNotice(`추가했습니다: ${t.name}`); }}
                        onDeleted={() => undefined}
                        onCancel={() => open({ kind: 'none' })} />
                )}
                {mode.kind === 'edit' && selected && (
                    <TermEditor key={selected.id} term={selected} terms={terms ?? []} targets={targets}
                        onSaved={(t) => { void reload(); setNotice(`저장했습니다: ${t.name}`); }}
                        onDeleted={() => { void reload(); setMode({ kind: 'none' }); setNotice('용어를 지웠습니다.'); }}
                        onCancel={() => open({ kind: 'none' })} />
                )}
                {mode.kind === 'import' && (
                    <TermImport
                        onClose={() => open({ kind: 'none' })}
                        onImported={(s) => {
                            void reload();
                            setMode({ kind: 'none' });
                            setNotice(`가져오기 완료: 새 용어 ${s.created}개, 바뀐 용어 ${s.updated}개, 바뀜 없음 ${s.unchanged}개, 건너뜀 ${s.skipped}개`);
                        }} />
                )}
                {mode.kind === 'none' && <ResolvePreview />}
            </main>
        </div>
    );
}

/** 질문을 넣으면 용어집으로 어떻게 읽히는지 보여준다 (그래프 검색과 같은 규칙) */
function ResolvePreview() {
    const [query, setQuery] = useState('');
    const [result, setResult] = useState<{ query: string; terms: ResolvedTerm[] } | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    async function run() {
        if (!query.trim()) return;
        setBusy(true);
        setError('');
        try {
            setResult(await termApi.resolve(query.trim()));
        } catch (e) {
            setError(errorMessage(e, '확인하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="max-w-2xl space-y-4">
            <div>
                <h2 className="text-[15px] font-bold">질문 해석 미리보기</h2>
                <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    질문에 용어집의 표기가 나오면 그래프 검색이 그 용어의 표준 이름과 모든 표기로 개체를 찾습니다.
                    용어집은 그래프에 쓰지 않습니다. 그래프는 문서와 사양 DB로만 만듭니다.
                </p>
            </div>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void run(); }}>
                <input className={inputCls} placeholder="예: N5800 전자파 인증 자료 보내주세요" aria-label="확인할 질문" value={query} onChange={(e) => setQuery(e.target.value)} />
                <button type="submit" className={`${btnPrimary} shrink-0 whitespace-nowrap`} disabled={busy || !query.trim()}>확인</button>
            </form>
            {error && <Notice kind="error">{error}</Notice>}
            {result && (result.terms.length === 0 ? (
                <p className="text-[12.5px] text-muted">이 질문에서 찾은 용어가 없습니다. 그래프 검색은 질문에 적힌 표기로만 찾습니다.</p>
            ) : (
                <ul className="space-y-2">
                    {result.terms.map((t) => (
                        <li key={t.id} className="rounded-xl border border-divide px-4 py-3 text-[12.5px] leading-relaxed">
                            <div>
                                <span className="font-semibold">"{t.matched}"</span>
                                <span className="text-muted"> → </span>
                                <span className="font-bold">{t.name}</span>
                                {t.target_text && <span className="ml-2"><Pill>{t.target_text}</Pill></span>}
                            </div>
                            {t.kind === 'bundle' && <div className="mt-1"><Pill tone="brand">묶음</Pill> <span className="text-muted">구성 용어마다 따로 찾습니다</span></div>}
                            <div className="mt-1 text-muted">찾는 표기: {t.aliases.join(', ')}</div>
                            <EntityLine entities={t.graph_entities} quiet={t.kind === 'bundle'} />
                            {t.members.length > 0 && (
                                <ul className="mt-2 space-y-1.5 border-l-2 border-divide pl-3">
                                    {t.members.map((m) => (
                                        <li key={m.id}>
                                            <span className="font-semibold">{m.name}</span>
                                            {m.target_text && <span className="ml-2"><Pill>{m.target_text}</Pill></span>}
                                            <div className="text-muted">찾는 표기: {m.aliases.join(', ')}</div>
                                            <EntityLine entities={m.graph_entities} />
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </li>
                    ))}
                </ul>
            ))}
        </div>
    );
}

/** 그 표기로 찾은 그래프 개체. quiet면 없을 때 경고 없이 넘어간다 (묶음 이름 자체는 개체가 아닌 경우가 많다) */
function EntityLine({ entities, quiet = false }: { entities: { name: string }[]; quiet?: boolean }) {
    if (entities.length === 0 && quiet) return null;
    return (
        <div className="mt-1">
            그래프 개체: {entities.length
                ? entities.map((e) => e.name).join(', ')
                : <span className="text-warn">없음 (그래프에 이 표기의 개체가 없습니다. 모델은 표기로 문서를 검색합니다)</span>}
        </div>
    );
}
