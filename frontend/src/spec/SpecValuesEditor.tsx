import { useState } from 'react';
import { TrashIcon } from '../components/icons';
import { specApi, type OwnerType, type SpecAttribute, type SpecMeta, type SpecValue, type SpecValueInput } from './api';
import { attributesFor, btnPrimary, btnTiny, errorMessage, labelOf, smallInputCls } from './styles';
import { Notice, Pill } from './ui';

/**
 * 제품 또는 부품 하나의 사양 값 표. 분류별로 묶어 보여주고, 행을 눌러 바로 고치거나 지운다.
 * 맨 아래 입력 줄로 새 값을 넣는다. 같은 속성에 기본값과 옵션값을 각각 한 행으로 넣는다.
 */

const EMPTY: SpecValueInput = { attribute_key: '', value_text: '', is_option: false, note: '', source_page: null, source_note: '' };

function placeholderFor(attribute: SpecAttribute | undefined): string {
    if (!attribute) return '값';
    if (attribute.data_type === 'number') return attribute.unit ? `숫자 (${attribute.unit})` : '숫자';
    if (attribute.data_type === 'bool') return '예 / 아니오';
    return '값';
}

function toInput(spec: SpecValue): SpecValueInput {
    return {
        attribute_key: spec.attribute_key,
        value_text: spec.value_text,
        is_option: spec.is_option,
        note: spec.note,
        source_page: spec.source_page,
        source_note: spec.source_note,
    };
}

export function SpecValuesEditor({
    ownerType,
    ownerId,
    specs,
    attributes,
    meta,
    scope,
    onChanged,
    onAddDefaultAttributes,
}: {
    ownerType: OwnerType;
    ownerId: string;
    specs: SpecValue[];
    attributes: SpecAttribute[];
    meta: SpecMeta | null;
    /** 'product' 또는 부품 종류. 선택 목록을 이 대상에 맞는 속성으로 추린다 */
    scope: string;
    /** 값이 바뀌었으니 소유자 상세를 다시 불러오라는 신호 */
    onChanged: () => void;
    onAddDefaultAttributes?: () => Promise<void>;
}) {
    const [draft, setDraft] = useState<SpecValueInput>(EMPTY);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editDraft, setEditDraft] = useState<SpecValueInput>(EMPTY);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [showAll, setShowAll] = useState(false);

    const attributeOf = (key: string) => attributes.find((a) => a.key === key);
    // SSD면 저장장치 분류처럼 대상에 맞는 속성만 보여준다. 필요하면 "모든 속성"으로 전부 연다
    const scopedAttributes = showAll ? attributes : attributesFor(attributes, scope);
    const hiddenCount = attributes.length - scopedAttributes.length;
    const categories = meta ? Object.keys(meta.attribute_categories) : [];
    const categoryOrder = (c: string) => { const i = categories.indexOf(c); return i < 0 ? 99 : i; };

    // 분류별로 묶는다 (서버 정렬을 따르되 분류 헤더를 끼운다)
    const grouped = new Map<string, SpecValue[]>();
    for (const s of [...specs].sort((a, b) => categoryOrder(a.category) - categoryOrder(b.category))) {
        grouped.set(s.category, [...(grouped.get(s.category) ?? []), s]);
    }

    // 속성 선택 목록도 분류별 optgroup
    const attributeGroups = new Map<string, SpecAttribute[]>();
    for (const a of scopedAttributes) attributeGroups.set(a.category, [...(attributeGroups.get(a.category) ?? []), a]);

    async function run(action: () => Promise<unknown>, fallback: string) {
        setBusy(true);
        setError('');
        try {
            await action();
            onChanged();
            return true;
        } catch (e) {
            setError(errorMessage(e, fallback));
            return false;
        } finally {
            setBusy(false);
        }
    }

    const add = async () => {
        if (!draft.attribute_key || !draft.value_text.trim()) return;
        const ok = await run(() => specApi.addValue({ owner_type: ownerType, owner_id: ownerId }, draft), '사양 값을 추가하지 못했습니다.');
        if (ok) setDraft((d) => ({ ...EMPTY, attribute_key: d.attribute_key })); // 같은 속성에 옵션을 이어서 넣기 쉽게 속성은 남긴다
    };

    const saveEdit = async () => {
        if (editingId === null || !editDraft.value_text.trim()) return;
        const ok = await run(() => specApi.updateValue(editingId, editDraft), '사양 값을 저장하지 못했습니다.');
        if (ok) setEditingId(null);
    };

    const remove = async (spec: SpecValue) => {
        if (!window.confirm(`'${spec.attribute_name} = ${spec.value_text}' 값을 삭제할까요?`)) return;
        await run(() => specApi.deleteValue(spec.id), '사양 값을 삭제하지 못했습니다.');
    };

    const selectedAttribute = attributeOf(draft.attribute_key);

    return (
        <div>
            {error && <div className="mb-3"><Notice kind="error">{error}</Notice></div>}

            {specs.length === 0 ? (
                <p className="text-[12.5px] text-muted py-2">아직 등록된 사양 값이 없습니다. 아래에서 속성을 고르고 값을 넣으세요.</p>
            ) : (
                <table className="w-full text-[12.5px]">
                    <thead>
                        <tr className="text-left text-[11px] text-muted">
                            <th className="py-1.5 pr-3 font-semibold">속성</th>
                            <th className="py-1.5 pr-3 font-semibold">값</th>
                            <th className="py-1.5 pr-3 font-semibold">비고</th>
                            <th className="py-1.5 pr-3 font-semibold">출처</th>
                            <th className="py-1.5 w-[88px]" />
                        </tr>
                    </thead>
                    <tbody>
                        {[...grouped.entries()].map(([category, rows]) => (
                            <GroupRows
                                key={category}
                                title={labelOf(meta?.attribute_categories, category)}
                                rows={rows}
                                editingId={editingId}
                                editDraft={editDraft}
                                busy={busy}
                                attributeOf={attributeOf}
                                onStartEdit={(s) => { setEditingId(s.id); setEditDraft(toInput(s)); setError(''); }}
                                onEditChange={(patch) => setEditDraft((d) => ({ ...d, ...patch }))}
                                onSave={() => void saveEdit()}
                                onCancel={() => setEditingId(null)}
                                onRemove={(s) => void remove(s)}
                            />
                        ))}
                    </tbody>
                </table>
            )}

            {/* 새 값 입력 */}
            <div className="mt-4 rounded-xl border border-dashed border-line bg-surface px-3 py-3">
                {attributes.length === 0 ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
                        <span className="text-muted">속성 사전이 비어 있어 값을 넣을 수 없습니다. 속성 탭에서 만들거나 기본 속성을 추가하세요.</span>
                        {onAddDefaultAttributes && (
                            <button type="button" onClick={() => void onAddDefaultAttributes()} className={btnPrimary}>기본 속성 추가</button>
                        )}
                    </div>
                ) : (
                    <>
                        <div className="flex items-center justify-between gap-2">
                            <p className="text-[11.5px] font-semibold text-muted">사양 값 추가</p>
                            {hiddenCount > 0 || showAll ? (
                                <label className="inline-flex items-center gap-1.5 text-[11px] text-muted">
                                    <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="accent-brand" />
                                    모든 속성 보기{!showAll && ` (+${hiddenCount})`}
                                </label>
                            ) : null}
                        </div>
                        <div className="mt-2 grid grid-cols-1 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] gap-2">
                            <select
                                value={draft.attribute_key}
                                onChange={(e) => setDraft((d) => ({ ...d, attribute_key: e.target.value }))}
                                disabled={busy}
                                aria-label="속성"
                                className={smallInputCls}
                            >
                                <option value="">속성 선택…</option>
                                {[...attributeGroups.entries()].sort((a, b) => categoryOrder(a[0]) - categoryOrder(b[0])).map(([category, list]) => (
                                    <optgroup key={category} label={labelOf(meta?.attribute_categories, category)}>
                                        {list.map((a) => (
                                            <option key={a.key} value={a.key}>{a.name}{a.unit ? ` (${a.unit})` : ''}</option>
                                        ))}
                                    </optgroup>
                                ))}
                            </select>
                            <input
                                value={draft.value_text}
                                onChange={(e) => setDraft((d) => ({ ...d, value_text: e.target.value }))}
                                onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void add(); } }}
                                disabled={busy}
                                placeholder={placeholderFor(selectedAttribute)}
                                aria-label="값"
                                className={smallInputCls}
                            />
                            <label className="inline-flex h-8 items-center gap-1.5 text-[12px] text-ink whitespace-nowrap">
                                <input type="checkbox" checked={draft.is_option} onChange={(e) => setDraft((d) => ({ ...d, is_option: e.target.checked }))} disabled={busy} className="accent-brand" />
                                옵션 구성
                            </label>
                        </div>
                        <div className="mt-2 grid grid-cols-1 sm:grid-cols-[minmax(0,1.4fr)_88px_minmax(0,1fr)_auto] gap-2">
                            <input value={draft.note} onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))} disabled={busy} placeholder="비고 (예: 공유 메모리)" aria-label="비고" className={smallInputCls} />
                            <input
                                type="number"
                                min={1}
                                value={draft.source_page ?? ''}
                                onChange={(e) => setDraft((d) => ({ ...d, source_page: e.target.value ? Number(e.target.value) : null }))}
                                disabled={busy}
                                placeholder="쪽"
                                aria-label="근거 페이지"
                                className={smallInputCls}
                            />
                            <input value={draft.source_note} onChange={(e) => setDraft((d) => ({ ...d, source_note: e.target.value }))} disabled={busy} placeholder="출처 (예: Sales Guide V1.3, R&D 홍길동)" aria-label="출처 메모" className={smallInputCls} />
                            <button type="button" onClick={() => void add()} disabled={busy || !draft.attribute_key || !draft.value_text.trim()} className={`${btnPrimary} !h-8`}>
                                {busy ? '저장 중…' : '추가'}
                            </button>
                        </div>
                        {selectedAttribute?.description && <p className="mt-1.5 text-[11px] text-muted">{selectedAttribute.description}</p>}
                    </>
                )}
            </div>
        </div>
    );
}

function GroupRows({
    title,
    rows,
    editingId,
    editDraft,
    busy,
    attributeOf,
    onStartEdit,
    onEditChange,
    onSave,
    onCancel,
    onRemove,
}: {
    title: string;
    rows: SpecValue[];
    editingId: number | null;
    editDraft: SpecValueInput;
    busy: boolean;
    attributeOf: (key: string) => SpecAttribute | undefined;
    onStartEdit: (s: SpecValue) => void;
    onEditChange: (patch: Partial<SpecValueInput>) => void;
    onSave: () => void;
    onCancel: () => void;
    onRemove: (s: SpecValue) => void;
}) {
    return (
        <>
            <tr>
                <td colSpan={5} className="pt-3 pb-1 text-[11px] font-bold text-muted">{title}</td>
            </tr>
            {rows.map((s) => {
                const editing = editingId === s.id;
                return (
                    <tr key={s.id} className="border-t border-divide align-top">
                        <td className="py-2 pr-3">
                            <span className="font-semibold">{s.attribute_name}</span>
                            {s.is_option && !editing && <span className="ml-1.5"><Pill tone="warn">옵션</Pill></span>}
                        </td>
                        {editing ? (
                            <>
                                <td className="py-1.5 pr-3">
                                    <input
                                        value={editDraft.value_text}
                                        onChange={(e) => onEditChange({ value_text: e.target.value })}
                                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); onSave(); } if (e.key === 'Escape') onCancel(); }}
                                        disabled={busy}
                                        placeholder={placeholderFor(attributeOf(s.attribute_key))}
                                        aria-label="값"
                                        className={smallInputCls}
                                    />
                                    <label className="mt-1.5 inline-flex items-center gap-1.5 text-[11.5px]">
                                        <input type="checkbox" checked={editDraft.is_option} onChange={(e) => onEditChange({ is_option: e.target.checked })} disabled={busy} className="accent-brand" />
                                        옵션 구성
                                    </label>
                                </td>
                                <td className="py-1.5 pr-3">
                                    <input value={editDraft.note} onChange={(e) => onEditChange({ note: e.target.value })} disabled={busy} placeholder="비고" aria-label="비고" className={smallInputCls} />
                                </td>
                                <td className="py-1.5 pr-3">
                                    <div className="flex gap-1.5">
                                        <input type="number" min={1} value={editDraft.source_page ?? ''} onChange={(e) => onEditChange({ source_page: e.target.value ? Number(e.target.value) : null })} disabled={busy} placeholder="쪽" aria-label="근거 페이지" className={`${smallInputCls} w-[64px]`} />
                                        <input value={editDraft.source_note} onChange={(e) => onEditChange({ source_note: e.target.value })} disabled={busy} placeholder="출처" aria-label="출처 메모" className={smallInputCls} />
                                    </div>
                                </td>
                                <td className="py-1.5 text-right whitespace-nowrap">
                                    <button type="button" onClick={onSave} disabled={busy || !editDraft.value_text.trim()} className={`${btnTiny} text-brand hover:text-brand-hover`}>저장</button>
                                    <button type="button" onClick={onCancel} disabled={busy} className={btnTiny}>취소</button>
                                </td>
                            </>
                        ) : (
                            <>
                                <td className="py-2 pr-3 tabular-nums">
                                    {s.value_text}
                                    {s.data_type === 'number' && s.unit && !s.value_text.includes(s.unit) && <span className="ml-1 text-muted">{s.unit}</span>}
                                </td>
                                <td className="py-2 pr-3 text-muted break-words">{s.note || '—'}</td>
                                <td className="py-2 pr-3 text-muted break-words">
                                    {[s.source_note, s.source_page ? `${s.source_page}쪽` : ''].filter(Boolean).join(' · ') || '—'}
                                </td>
                                <td className="py-1.5 text-right whitespace-nowrap">
                                    <button type="button" onClick={() => onStartEdit(s)} disabled={busy} className={btnTiny}>수정</button>
                                    <button type="button" onClick={() => onRemove(s)} disabled={busy} aria-label="삭제" title="삭제" className={`${btnTiny} hover:text-danger`}>
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
