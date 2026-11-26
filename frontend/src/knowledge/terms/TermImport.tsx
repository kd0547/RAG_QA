import { useState } from 'react';
import { ApiError } from '../../lib/http';
import { btnGhost, btnPrimary, errorMessage, inputCls, smallInputCls } from '../../spec/styles';
import { Notice, Pill } from '../../spec/ui';
import { splitAliases, termApi, type ImportPlan, type ImportStatus, type ImportSummary, type PlannedRow } from './api';

const STATUS: Record<ImportStatus, { label: string; tone: 'muted' | 'brand' | 'warn' }> = {
    new: { label: '새 용어', tone: 'brand' },
    update: { label: '바뀜', tone: 'brand' },
    unchanged: { label: '바뀜 없음', tone: 'muted' },
    conflict: { label: '충돌', tone: 'warn' },
    error: { label: '오류', tone: 'warn' },
    skip: { label: '건너뜀', tone: 'muted' },
};

function blocked(row: PlannedRow): boolean {
    return !row.skip && (row.status === 'conflict' || row.status === 'error');
}

/**
 * 엑셀·붙여넣기로 용어 가져오기.
 * 1) 파일을 올리거나 표를 붙여넣으면 미리보기를 만든다 (저장 안 함)
 * 2) 미리보기 표에서 고치거나 건너뛰기를 고른 뒤 [다시 확인] → 충돌·오류가 없으면 [저장]
 * 기존 용어는 표기를 더하기만 한다. 엑셀에 없는 표기를 지우지 않고, 빈 칸은 기존 값을 지우지 않는다.
 */
export function TermImport({ onImported, onClose }: { onImported: (summary: ImportSummary) => void; onClose: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [text, setText] = useState('');
    const [plan, setPlan] = useState<ImportPlan | null>(null);
    /** 미리보기에서 고친 뒤 아직 다시 확인하지 않았다 */
    const [dirty, setDirty] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
        setBusy(true);
        setError('');
        try {
            return await work();
        } catch (e) {
            // 저장 거절(400)이면 서버가 다시 대조한 행을 함께 준다
            const rows = e instanceof ApiError && e.detail && typeof e.detail === 'object' ? (e.detail as { rows?: PlannedRow[] }).rows : undefined;
            if (rows && plan) setPlan({ ...plan, rows });
            setError(errorMessage(e, '처리하지 못했습니다.'));
            return undefined;
        } finally {
            setBusy(false);
        }
    }

    async function preview() {
        const result = await run(() => termApi.parse(file ? { file } : { text }));
        if (result) {
            setPlan(result);
            setDirty(false);
        }
    }

    async function recheck() {
        if (!plan) return;
        const result = await run(() => termApi.check(plan.source, plan.rows));
        if (result) {
            setPlan(result);
            setDirty(false);
        }
    }

    async function save() {
        if (!plan) return;
        const summary = await run(() => termApi.apply(plan.source, plan.rows));
        if (summary) onImported(summary);
    }

    function edit(index: number, change: Partial<PlannedRow>) {
        if (!plan) return;
        setPlan({ ...plan, rows: plan.rows.map((r) => (r.index === index ? { ...r, ...change } : r)) });
        setDirty(true);
    }

    const blockedCount = plan ? plan.rows.filter(blocked).length : 0;
    const savable = plan ? plan.rows.filter((r) => !r.skip && (r.status === 'new' || r.status === 'update')).length : 0;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <h2 className="text-[15px] font-bold">엑셀 가져오기</h2>
                    <p className="mt-1 text-[12px] text-muted">
                        시트 한 장, 첫 행 머리글: 표준 이름 | 다른 표기 | 종류 | 구성 용어 | 연결 대상 | 설명. 다른 표기·구성 용어는 쉼표로 나눕니다.
                        종류는 용어 또는 묶음 (비우면 구성 용어가 있을 때 묶음). 구성 용어는 같은 표의 행이나 등록된 용어 이름으로 씁니다.
                        연결 대상은 "그래프:인증", "사양:메모리 용량"처럼 씁니다.
                    </p>
                </div>
                <div className="flex gap-2">
                    <a href={termApi.templateUrl()} download className={btnGhost}>양식 받기 (등록된 용어 포함)</a>
                    <button type="button" className={btnGhost} onClick={onClose}>닫기</button>
                </div>
            </div>

            {!plan && (
                <div className="grid gap-3 md:grid-cols-2">
                    <label className="block rounded-xl border border-dashed border-line p-4 text-[12.5px]">
                        <span className="font-semibold">엑셀 파일 (.xlsx)</span>
                        <input type="file" accept=".xlsx,.xlsm" className="mt-2 block w-full text-[12px]"
                            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setText(''); }} />
                    </label>
                    <label className="block text-[12.5px]">
                        <span className="font-semibold">또는 엑셀에서 복사해 붙여넣기</span>
                        <textarea rows={5} className={`${inputCls} mt-2 h-auto py-2 font-mono text-[12px]`} value={text}
                            placeholder={'표준 이름\t다른 표기\t종류\t구성 용어\t연결 대상\t설명\n적합성 등록\t전자파 인증, KC 전파\t용어\t\t그래프:인증\t\nKC 인증 자료\tKC 인증\t묶음\t적합성 등록, 안전확인 신고\t\t'}
                            onChange={(e) => { setText(e.target.value); setFile(null); }} />
                    </label>
                    <div className="md:col-span-2">
                        <button type="button" className={btnPrimary} disabled={busy || (!file && !text.trim())} onClick={() => void preview()}>
                            {busy ? '읽는 중…' : '미리보기'}
                        </button>
                    </div>
                </div>
            )}

            {error && <Notice kind="error">{error}</Notice>}

            {plan && (
                <>
                    <div className="flex flex-wrap items-center gap-2 text-[12px]">
                        <span className="font-semibold">{plan.source}</span>
                        {(Object.keys(STATUS) as ImportStatus[]).filter((s) => plan.counts[s]).map((s) => (
                            <Pill key={s} tone={STATUS[s].tone}>{STATUS[s].label} {plan.counts[s]}</Pill>
                        ))}
                        {dirty && <span className="text-warn">고친 내용이 있습니다. [다시 확인]을 누르세요.</span>}
                    </div>

                    <div className="overflow-x-auto rounded-xl border border-divide">
                        <table className="w-full min-w-[1500px] table-fixed text-left text-[12px]">
                            <thead className="bg-surface text-[11px] text-muted">
                                <tr>
                                    <th className="px-2 py-2 w-12">행</th>
                                    <th className="px-2 py-2 w-20">상태</th>
                                    <th className="px-2 py-2 w-44">표준 이름</th>
                                    <th className="px-2 py-2 w-64">다른 표기</th>
                                    <th className="px-2 py-2 w-20">종류</th>
                                    <th className="px-2 py-2 w-64">구성 용어</th>
                                    <th className="px-2 py-2 w-36">연결 대상</th>
                                    <th className="px-2 py-2 w-48">설명</th>
                                    <th className="px-2 py-2 w-56">알림</th>
                                    <th className="px-2 py-2 w-16">건너뛰기</th>
                                </tr>
                            </thead>
                            <tbody>
                                {plan.rows.map((row) => (
                                    <tr key={row.index} className={`border-t border-divide align-top ${blocked(row) ? 'bg-warn-soft/40' : ''} ${row.skip ? 'opacity-50' : ''}`}>
                                        <td className="px-2 py-1.5 tabular-nums text-muted">{row.line ?? row.index + 1}</td>
                                        <td className="px-2 py-1.5"><Pill tone={STATUS[row.status].tone}>{STATUS[row.status].label}</Pill></td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="표준 이름" className={smallInputCls} value={row.name} onChange={(e) => edit(row.index, { name: e.target.value })} />
                                        </td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="다른 표기" className={smallInputCls} defaultValue={row.aliases.join(', ')}
                                                key={`${row.index}:${row.aliases.join('|')}`}
                                                onBlur={(e) => {
                                                    const next = splitAliases(e.target.value);
                                                    if (next.join('|') !== row.aliases.join('|')) edit(row.index, { aliases: next });
                                                }} />
                                        </td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="종류" placeholder={row.members.length ? '묶음' : '용어'} className={smallInputCls} value={row.kind}
                                                onChange={(e) => edit(row.index, { kind: e.target.value })} />
                                        </td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="구성 용어" className={smallInputCls} defaultValue={row.members.join(', ')}
                                                key={`m${row.index}:${row.members.join('|')}`}
                                                onBlur={(e) => {
                                                    const next = splitAliases(e.target.value);
                                                    if (next.join('|') !== row.members.join('|')) edit(row.index, { members: next });
                                                }} />
                                        </td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="연결 대상" className={smallInputCls} value={row.target} onChange={(e) => edit(row.index, { target: e.target.value })} />
                                        </td>
                                        <td className="px-2 py-1.5">
                                            <input aria-label="설명" className={smallInputCls} value={row.description} onChange={(e) => edit(row.index, { description: e.target.value })} />
                                        </td>
                                        <td className="px-2 py-1.5 leading-relaxed">
                                            {row.term_name && row.status !== 'new' && <div className="text-muted">기존 용어: {row.term_name}</div>}
                                            {row.changes.map((c) => <div key={c}>{c}</div>)}
                                            {row.messages.map((m) => <div key={m} className="text-danger">{m}</div>)}
                                        </td>
                                        <td className="px-2 py-1.5 text-center">
                                            <input type="checkbox" aria-label="이 행 건너뛰기" checked={row.skip} onChange={(e) => edit(row.index, { skip: e.target.checked })} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        <button type="button" className={btnGhost} disabled={busy} onClick={() => void recheck()}>다시 확인</button>
                        <button type="button" className={btnPrimary} disabled={busy || dirty || blockedCount > 0 || savable === 0} onClick={() => void save()}>
                            저장 ({savable}개)
                        </button>
                        <button type="button" className={btnGhost} disabled={busy} onClick={() => { setPlan(null); setError(''); }}>다른 표 고르기</button>
                        {blockedCount > 0 && !dirty && (
                            <span className="text-[12px] text-warn">충돌·오류 {blockedCount}행: 표에서 고치거나 건너뛰기를 고른 뒤 다시 확인하세요.</span>
                        )}
                    </div>
                </>
            )}
        </div>
    );
}
