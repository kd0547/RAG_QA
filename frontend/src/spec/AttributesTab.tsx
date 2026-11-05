import { useState } from 'react';
import { TrashIcon } from '../components/icons';
import { specApi, type AttributeInput, type DataType, type SpecAttribute, type SpecMeta } from './api';
import { btnGhost, btnPrimary, btnTiny, errorMessage, labelOf, smallInputCls } from './styles';
import { Notice } from './ui';

const EMPTY: AttributeInput = { key: '', name: '', category: 'other', data_type: 'text', unit: '', description: '', sort_order: 0 };
type Editable = Omit<AttributeInput, 'key'>;

/**
 * 속성 사전 탭. 제품·부품 사양 값은 여기 있는 키로만 저장되고, 비교 코드는 자료형과 단위를 본다.
 * 기본 속성은 서버가 자동으로 넣지 않으므로 "기본 속성 추가"로 가져온다.
 */
export function AttributesTab({
    meta,
    attributes,
    onChanged,
    onAddDefaults,
}: {
    meta: SpecMeta | null;
    attributes: SpecAttribute[] | null;
    onChanged: () => Promise<void>;
    onAddDefaults: () => Promise<void>;
}) {
    const [adding, setAdding] = useState(false);
    const [draft, setDraft] = useState<AttributeInput>(EMPTY);
    const [editingKey, setEditingKey] = useState<string | null>(null);
    const [editDraft, setEditDraft] = useState<Editable>(EMPTY);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const categories = Object.entries(meta?.attribute_categories ?? {});
    const dataTypes = Object.entries(meta?.data_types ?? {}) as [DataType, string][];

    async function run(action: () => Promise<string>, fallback: string): Promise<boolean> {
        setBusy(true);
        setNotice('');
        setError('');
        try {
            const message = await action();
            await onChanged();
            setNotice(message);
            return true;
        } catch (e) {
            setError(errorMessage(e, fallback));
            return false;
        } finally {
            setBusy(false);
        }
    }

    const addDefaults = () => run(async () => { await onAddDefaults(); return '기본 속성을 추가했습니다. 이미 있던 속성은 그대로 두었습니다.'; }, '기본 속성을 추가하지 못했습니다.');

    const create = async () => {
        const ok = await run(async () => {
            const saved = await specApi.createAttribute({ ...draft, key: draft.key.trim().toLowerCase(), sort_order: Number(draft.sort_order) || 0 });
            return `'${saved.name}' 속성을 추가했습니다.`;
        }, '속성을 추가하지 못했습니다.');
        if (ok) { setDraft(EMPTY); setAdding(false); }
    };

    const saveEdit = async () => {
        if (!editingKey) return;
        const ok = await run(async () => {
            await specApi.updateAttribute(editingKey, { ...editDraft, sort_order: Number(editDraft.sort_order) || 0 });
            return '저장했습니다.';
        }, '속성을 저장하지 못했습니다.');
        if (ok) setEditingKey(null);
    };

    const remove = async (a: SpecAttribute) => {
        if (!window.confirm(`'${a.name}' (${a.key}) 속성을 삭제할까요?`)) return;
        await run(async () => { await specApi.deleteAttribute(a.key); return `'${a.name}' 속성을 삭제했습니다.`; }, '속성을 삭제하지 못했습니다.');
    };

    const startEdit = (a: SpecAttribute) => {
        setEditingKey(a.key);
        setEditDraft({ name: a.name, category: a.category, data_type: a.data_type, unit: a.unit, description: a.description, sort_order: a.sort_order });
        setNotice('');
        setError('');
    };

    const categoryOrder = (c: string) => { const i = categories.findIndex(([k]) => k === c); return i < 0 ? 99 : i; };
    const grouped = new Map<string, SpecAttribute[]>();
    for (const a of attributes ?? []) grouped.set(a.category, [...(grouped.get(a.category) ?? []), a]);

    const canCreate = !busy && /^[a-z][a-z0-9_]{1,49}$/.test(draft.key.trim().toLowerCase()) && draft.name.trim().length > 0;

    return (
        <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8">
            <div className="mx-auto max-w-[1100px]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h1 className="text-[22px] font-bold tracking-tight">속성 사전 <span className="text-muted">{attributes?.length ?? ''}</span></h1>
                        <p className="mt-1.5 text-[12.5px] leading-6 text-muted max-w-[640px]">
                            제품과 부품의 사양 값은 여기 있는 속성 키로만 저장합니다. 숫자 속성은 단위를 적어 두면 입찰 조건의 "이상·이하" 비교에 그대로 쓰입니다.
                            사용 중인 속성은 지울 수 없고, 자료형을 바꾸면 기존 값이 새 자료형으로 읽히는지 서버가 확인합니다.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button type="button" onClick={() => void addDefaults()} disabled={busy} className={btnGhost}>기본 속성 추가</button>
                        <button type="button" onClick={() => { setAdding((v) => !v); setNotice(''); setError(''); }} disabled={busy} className={btnPrimary}>{adding ? '닫기' : '+ 새 속성'}</button>
                    </div>
                </div>

                <div className="mt-4 flex flex-col gap-2">
                    {notice && <Notice kind="ok">{notice}</Notice>}
                    {error && <Notice kind="error">{error}</Notice>}
                </div>

                {adding && (
                    <section aria-label="새 속성" className="mt-4 rounded-2xl border border-brand/25 bg-brand-tint px-4 py-4">
                        <p className="text-[12px] font-semibold">새 속성</p>
                        <div className="mt-2 grid grid-cols-2 md:grid-cols-[1.2fr_1.4fr_1fr_1fr_0.7fr_1.6fr_0.6fr] gap-2">
                            <input value={draft.key} onChange={(e) => setDraft((d) => ({ ...d, key: e.target.value }))} placeholder="키 (예: ram_max_gb)" aria-label="속성 키" className={`${smallInputCls} font-mono`} />
                            <input value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="이름 (예: 메모리 최대 용량)" aria-label="속성 이름" className={smallInputCls} />
                            <select value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))} aria-label="분류" className={smallInputCls}>
                                {categories.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                            </select>
                            <select value={draft.data_type} onChange={(e) => setDraft((d) => ({ ...d, data_type: e.target.value as DataType }))} aria-label="자료형" className={smallInputCls}>
                                {dataTypes.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                            </select>
                            <input value={draft.unit} onChange={(e) => setDraft((d) => ({ ...d, unit: e.target.value }))} placeholder="단위" aria-label="단위" className={smallInputCls} />
                            <input value={draft.description} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} placeholder="설명 (입력 예시 등)" aria-label="설명" className={smallInputCls} />
                            <input type="number" value={draft.sort_order} onChange={(e) => setDraft((d) => ({ ...d, sort_order: Number(e.target.value) }))} placeholder="순서" aria-label="정렬 순서" className={smallInputCls} />
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-2">
                            <p className="text-[11px] text-muted">키는 영문 소문자로 시작하고 영문 소문자·숫자·_ 만 씁니다. 저장 후에는 바꿀 수 없습니다.</p>
                            <button type="button" onClick={() => void create()} disabled={!canCreate} className={`${btnPrimary} !h-8`}>{busy ? '저장 중…' : '추가'}</button>
                        </div>
                    </section>
                )}

                <section className="mt-5 overflow-hidden rounded-2xl border border-divide bg-white">
                    {attributes === null ? (
                        <p className="px-5 py-6 text-[13px] text-muted">속성을 불러오는 중…</p>
                    ) : attributes.length === 0 ? (
                        <div className="px-5 py-10 text-center">
                            <p className="text-[14px] font-semibold">속성이 없습니다</p>
                            <p className="mt-1.5 text-[12.5px] text-muted">CPU 코어 수, 메모리 용량, 무게 등 입찰 사양서에 자주 나오는 항목을 기본 속성으로 한 번에 넣을 수 있습니다.</p>
                            <button type="button" onClick={() => void addDefaults()} disabled={busy} className={`${btnPrimary} mt-4`}>기본 속성 추가</button>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[860px] text-[12.5px]">
                                <thead className="bg-surface text-left text-[11px] text-muted">
                                    <tr>
                                        <th className="px-4 py-2.5 font-semibold">키</th>
                                        <th className="px-3 py-2.5 font-semibold">이름</th>
                                        <th className="px-3 py-2.5 font-semibold">자료형</th>
                                        <th className="px-3 py-2.5 font-semibold">단위</th>
                                        <th className="px-3 py-2.5 font-semibold">설명</th>
                                        <th className="px-3 py-2.5 font-semibold text-right">사용</th>
                                        <th className="px-3 py-2.5 w-[96px]" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {[...grouped.entries()].sort((a, b) => categoryOrder(a[0]) - categoryOrder(b[0])).map(([category, rows]) => (
                                        <AttributeGroup
                                            key={category}
                                            title={labelOf(meta?.attribute_categories, category)}
                                            rows={rows}
                                            meta={meta}
                                            editingKey={editingKey}
                                            editDraft={editDraft}
                                            busy={busy}
                                            onStartEdit={startEdit}
                                            onEditChange={(patch) => setEditDraft((d) => ({ ...d, ...patch }))}
                                            onSave={() => void saveEdit()}
                                            onCancel={() => setEditingKey(null)}
                                            onRemove={(a) => void remove(a)}
                                        />
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </section>
            </div>
        </main>
    );
}

function AttributeGroup({
    title,
    rows,
    meta,
    editingKey,
    editDraft,
    busy,
    onStartEdit,
    onEditChange,
    onSave,
    onCancel,
    onRemove,
}: {
    title: string;
    rows: SpecAttribute[];
    meta: SpecMeta | null;
    editingKey: string | null;
    editDraft: Editable;
    busy: boolean;
    onStartEdit: (a: SpecAttribute) => void;
    onEditChange: (patch: Partial<Editable>) => void;
    onSave: () => void;
    onCancel: () => void;
    onRemove: (a: SpecAttribute) => void;
}) {
    const categories = Object.entries(meta?.attribute_categories ?? {});
    const dataTypes = Object.entries(meta?.data_types ?? {}) as [DataType, string][];
    return (
        <>
            <tr className="border-t border-divide">
                <td colSpan={7} className="px-4 pt-3 pb-1 text-[11px] font-bold text-muted">{title}</td>
            </tr>
            {rows.map((a) => {
                const editing = editingKey === a.key;
                return (
                    <tr key={a.key} className="border-t border-divide align-top">
                        <td className="px-4 py-2 font-mono text-[11.5px] text-muted whitespace-nowrap">{a.key}</td>
                        {editing ? (
                            <>
                                <td className="px-3 py-1.5">
                                    <input value={editDraft.name} onChange={(e) => onEditChange({ name: e.target.value })} disabled={busy} aria-label="이름" className={smallInputCls} />
                                    <select value={editDraft.category} onChange={(e) => onEditChange({ category: e.target.value })} disabled={busy} aria-label="분류" className={`${smallInputCls} mt-1.5`}>
                                        {categories.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                    </select>
                                </td>
                                <td className="px-3 py-1.5">
                                    <select value={editDraft.data_type} onChange={(e) => onEditChange({ data_type: e.target.value as DataType })} disabled={busy} aria-label="자료형" className={smallInputCls}>
                                        {dataTypes.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                    </select>
                                </td>
                                <td className="px-3 py-1.5"><input value={editDraft.unit} onChange={(e) => onEditChange({ unit: e.target.value })} disabled={busy} aria-label="단위" className={`${smallInputCls} w-[72px]`} /></td>
                                <td className="px-3 py-1.5">
                                    <input value={editDraft.description} onChange={(e) => onEditChange({ description: e.target.value })} disabled={busy} aria-label="설명" className={smallInputCls} />
                                    <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted">정렬
                                        <input type="number" value={editDraft.sort_order} onChange={(e) => onEditChange({ sort_order: Number(e.target.value) })} disabled={busy} aria-label="정렬 순서" className={`${smallInputCls} w-[64px]`} />
                                    </label>
                                </td>
                                <td className="px-3 py-2 text-right tabular-nums text-muted">{a.usage_count}</td>
                                <td className="px-3 py-1.5 text-right whitespace-nowrap">
                                    <button type="button" onClick={onSave} disabled={busy || !editDraft.name.trim()} className={`${btnTiny} text-brand hover:text-brand-hover`}>저장</button>
                                    <button type="button" onClick={onCancel} disabled={busy} className={btnTiny}>취소</button>
                                </td>
                            </>
                        ) : (
                            <>
                                <td className="px-3 py-2 font-semibold">{a.name}</td>
                                <td className="px-3 py-2 text-muted">{labelOf(meta?.data_types, a.data_type)}</td>
                                <td className="px-3 py-2 text-muted">{a.unit || '—'}</td>
                                <td className="px-3 py-2 text-muted break-words">{a.description || '—'}</td>
                                <td className="px-3 py-2 text-right tabular-nums text-muted">{a.usage_count}</td>
                                <td className="px-3 py-1.5 text-right whitespace-nowrap">
                                    <button type="button" onClick={() => onStartEdit(a)} disabled={busy} className={btnTiny}>수정</button>
                                    <button
                                        type="button"
                                        onClick={() => onRemove(a)}
                                        disabled={busy || a.usage_count > 0}
                                        title={a.usage_count > 0 ? `사양 값 ${a.usage_count}건이 쓰고 있어 지울 수 없습니다` : '삭제'}
                                        aria-label="삭제"
                                        className={`${btnTiny} hover:text-danger`}
                                    >
                                        <TrashIcon />
                                    </button>
                                </td>
                            </>
                        )}
                    </tr>
                );
            })}
        </>
    );
}
