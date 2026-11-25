import { useCallback, useEffect, useState } from 'react';
import { linkProps } from '../lib/router';
import { reviewPath } from '../mail/format';
import { skillApi, type AnalysisItem, type RequestType, type TypeList } from './api';
import { AuthorMissing, Chip, Dialog, DocStatusChip, ErrorBox } from './ui';
import { buttonOutline, errorMessage, formatDate, inputClass, TYPE_STATE_META } from './format';

export function TypesTab({ onOpenDraft }: { onOpenDraft: (docId: number) => void }) {
    const [data, setData] = useState<TypeList | null>(null);
    const [loadError, setLoadError] = useState('');
    const [busy, setBusy] = useState<number | null>(null);
    const [mergeFrom, setMergeFrom] = useState<RequestType | null>(null);
    const [mergeInto, setMergeInto] = useState<number | ''>('');
    const [mismatchOf, setMismatchOf] = useState<number | null>(null);
    const [mismatches, setMismatches] = useState<AnalysisItem[] | null>(null);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setLoadError('');
        try {
            setData(await skillApi.types());
        } catch (e) {
            setLoadError(errorMessage(e, '문의 유형을 불러오지 못했습니다.'));
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    async function act(typeId: number, action: () => Promise<string | void>, fallback: string) {
        setBusy(typeId);
        setNotice('');
        setError('');
        try {
            const message = await action();
            if (message) setNotice(message);
            await load();
        } catch (e) {
            setError(errorMessage(e, fallback));
        } finally {
            setBusy(null);
        }
    }

    const requestDraft = (t: RequestType) => act(t.type_id, async () => {
        const r = await skillApi.requestDraft(t.type_id);
        return r.already ? `'${t.label}' 유형은 이미 초안을 만드는 중입니다.` : `'${t.label}' ${r.message}`;
    }, '초안 생성을 요청하지 못했습니다.');

    const toggleState = (t: RequestType) => act(t.type_id, async () => {
        await skillApi.setTypeState(t.type_id, t.state === 'open' ? 'no_skill_needed' : 'open');
    }, '상태를 바꾸지 못했습니다.');

    async function merge() {
        if (!mergeFrom || mergeInto === '') return;
        const from = mergeFrom;
        await act(from.type_id, async () => {
            await skillApi.mergeType(from.type_id, mergeInto);
            setMergeFrom(null);
            setMergeInto('');
            return `'${from.label}' 유형을 합쳤습니다.`;
        }, '유형을 합치지 못했습니다.');
    }

    async function showMismatch(typeId: number) {
        if (mismatchOf === typeId) {
            setMismatchOf(null);
            return;
        }
        setMismatchOf(typeId);
        setMismatches(null);
        try {
            setMismatches((await skillApi.analysis({ typeId, mismatch: true, limit: 20 })).items);
        } catch (e) {
            setError(errorMessage(e, '어긋난 분석을 불러오지 못했습니다.'));
            setMismatchOf(null);
        }
    }

    const items = data?.items ?? [];
    const live = items.filter((t) => t.state !== 'merged');
    const merged = items.filter((t) => t.state === 'merged');
    const labelOf = (id: number | null) => items.find((t) => t.type_id === id)?.label ?? `#${id}`;

    return (
        <main className="flex-1 min-h-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8 lg:p-10">
            <div className="mx-auto max-w-[1080px]">
                <h1 className="text-[22px] font-bold tracking-tight">문의 유형</h1>
                <p className="mt-2 text-[13px] leading-6 text-muted">
                    저장된 메일 문의를 답변 뒤에 따로 분석해 유형을 나눕니다 (메일 처리가 없을 때 30초마다 몇 건씩).
                    SKILL이 없는 유형의 사례가 쌓이면 SKILL 초안이 만들어지고, R&D가 검토 대기 탭에서 승인합니다.
                    {data && <> 분석 {data.analysis.total}건{data.analysis.errors > 0 && <>, 실패 {data.analysis.errors}건</>}.</>}
                </p>
                {data && !data.author.available && <div className="mt-4"><AuthorMissing reason={data.author.reason} /></div>}
                <p role="status" className="mt-3 min-h-5 text-[12px] text-brand-hover">{notice}</p>
                {error && <p role="alert" className="mt-1 text-[12px] text-danger">{error}</p>}

                {loadError ? (
                    <div className="mt-3"><ErrorBox message={loadError} onRetry={() => void load()} /></div>
                ) : data === null ? (
                    <p className="mt-3 text-[13px] text-muted">불러오는 중…</p>
                ) : (
                    <ul className="mt-3 flex flex-col gap-3">
                        {live.map((t) => {
                            const draft = t.open_drafts[0];
                            const state = TYPE_STATE_META[t.state];
                            return (
                                <li key={t.type_id} className="rounded-2xl border border-divide bg-white p-5">
                                    <div className="flex flex-wrap items-start gap-3">
                                        <div className="min-w-0 flex-1">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <h2 className="text-[15px] font-bold">{t.label}</h2>
                                                <Chip className={state.chip}>{state.label}</Chip>
                                                {t.origin === 'seed' && <Chip className="border border-line bg-white text-muted">기본 유형</Chip>}
                                            </div>
                                            <p className="mt-1 text-[12.5px] leading-5 text-muted">{t.description}</p>
                                        </div>
                                        <div className="flex flex-wrap gap-4 text-[12px]">
                                            <Stat label="분석 건수" value={String(t.case_count)} />
                                            <Stat label="맡는 SKILL" value={t.skill_name ?? '없음'} muted={!t.skill_name} />
                                            <Stat
                                                label="분석·실제 사용 어긋남"
                                                value={String(t.mismatch_count)}
                                                muted={t.mismatch_count === 0}
                                                onClick={t.mismatch_count > 0 ? () => void showMismatch(t.type_id) : undefined}
                                            />
                                        </div>
                                    </div>

                                    {mismatchOf === t.type_id && (
                                        <div className="mt-3 rounded-xl bg-surface px-4 py-3 text-[12px]">
                                            <p className="text-muted">분석은 SKILL을 골랐는데 실제 답변 실행에서 그 SKILL을 읽지 않은 문의입니다.</p>
                                            {mismatches === null ? <p className="mt-2 text-muted">불러오는 중…</p> : (
                                                <ul className="mt-2 space-y-1">
                                                    {mismatches.map((m) => (
                                                        <li key={m.task_id} className="flex flex-wrap gap-2">
                                                            <a {...linkProps(reviewPath(m.task_id))} className="font-semibold hover:underline">{m.subject || '(제목 없음)'}</a>
                                                            <span className="text-muted">분석: {m.covered_by} · 실제: {m.used_skills.join(', ') || '없음'}</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    )}

                                    {t.recent_cases.length > 0 && (
                                        <ul className="mt-3 flex flex-col gap-1">
                                            {t.recent_cases.map((c) => (
                                                <li key={c.task_id} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                                                    <a {...linkProps(reviewPath(c.task_id))} className="min-w-0 truncate text-ink hover:text-brand-hover hover:underline">
                                                        {c.subject || '(제목 없음)'}
                                                    </a>
                                                    <span className="text-[11.5px] text-muted tabular-nums">{formatDate(c.received_at)}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    )}

                                    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-divide pt-3">
                                        {draft ? (
                                            <button type="button" onClick={() => onOpenDraft(draft.doc_id)} className={buttonOutline}>
                                                <DocStatusChip status={draft.status} /> 초안 보기{draft.name ? ` (${draft.name})` : ''}
                                            </button>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={() => void requestDraft(t)}
                                                disabled={!data.author.available || busy === t.type_id}
                                                title={data.author.available ? '이 유형의 사례로 SKILL 초안을 만듭니다 (건수 조건 없음)' : '작성 SKILL(create-skill)가 없어 만들 수 없습니다'}
                                                className={buttonOutline}
                                            >
                                                {t.has_rejected ? '초안 다시 만들기' : '초안 만들기'}
                                            </button>
                                        )}
                                        <button type="button" onClick={() => void toggleState(t)} disabled={busy === t.type_id} className={buttonOutline}>
                                            {t.state === 'open' ? 'SKILL 불필요로 표시' : 'SKILL 필요로 되돌리기'}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => { setMergeFrom(t); setMergeInto(''); }}
                                            disabled={busy === t.type_id || live.length < 2}
                                            className={buttonOutline}
                                        >
                                            다른 유형과 합치기
                                        </button>
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                )}

                {merged.length > 0 && (
                    <section aria-label="합쳐진 유형" className="mt-6">
                        <h2 className="text-[13px] font-semibold text-muted">합쳐진 유형</h2>
                        <ul className="mt-2 flex flex-wrap gap-2 text-[12px] text-muted">
                            {merged.map((t) => (
                                <li key={t.type_id} className="rounded-lg border border-divide bg-white px-3 py-1.5">
                                    {t.label} → {labelOf(t.merged_into)}
                                </li>
                            ))}
                        </ul>
                    </section>
                )}
            </div>

            {mergeFrom && (
                <Dialog
                    title={`'${mergeFrom.label}' 유형 합치기`}
                    confirmLabel="합치기"
                    confirmDisabled={mergeInto === ''}
                    busy={busy === mergeFrom.type_id}
                    onConfirm={() => void merge()}
                    onClose={() => setMergeFrom(null)}
                >
                    <p>이 유형으로 분석된 문의 {mergeFrom.case_count}건을 고른 유형으로 옮기고, 이 유형은 '합쳐짐'으로 둡니다.</p>
                    <label htmlFor="merge-into" className="mt-3 block text-[12px] font-semibold">합칠 유형</label>
                    <select
                        id="merge-into"
                        value={mergeInto}
                        onChange={(e) => setMergeInto(e.target.value ? Number(e.target.value) : '')}
                        className={`mt-1 h-9 ${inputClass}`}
                    >
                        <option value="">고르세요</option>
                        {live.filter((t) => t.type_id !== mergeFrom.type_id).map((t) => (
                            <option key={t.type_id} value={t.type_id}>{t.label} ({t.case_count}건)</option>
                        ))}
                    </select>
                </Dialog>
            )}
        </main>
    );
}

function Stat({ label, value, muted, onClick }: { label: string; value: string; muted?: boolean; onClick?: () => void }) {
    const content = (
        <>
            <span className="block text-[11px] text-muted">{label}</span>
            <span className={`block mt-0.5 text-[14px] font-bold tabular-nums ${muted ? 'text-muted' : 'text-ink'} ${onClick ? 'underline decoration-dotted' : ''}`}>{value}</span>
        </>
    );
    return onClick
        ? <button type="button" onClick={onClick} className="text-left focus-visible:outline-2 focus-visible:outline-brand">{content}</button>
        : <div>{content}</div>;
}
