import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { CloseIcon, TrashIcon } from '../components/icons';
import { specApi, type DataType, type OwnerType, type SpecAttribute, type SpecMeta, type SpecValue, type SpecValueInput } from './api';
import {
    attributesFor, autoAttributeKey, btnPrimary, btnTiny, defaultCategoryFor, errorMessage, labelOf, nextSortOrder,
    normalizeName, sameNameAttribute, smallInputCls,
} from './styles';
import { Notice, Pill } from './ui';

/**
 * 제품 또는 부품 하나의 사양 표. 속성이 행이고, 값 칸을 눌러 그 자리에서 바로 넣고 고친다.
 * - 처음에는 값이 있는 속성만 보인다. "속성·값 찾기"에 이름을 치면 빈 속성도 찾아지고, "빈 속성도 보기"로 전부 펼친다.
 * - 찾는 속성이 사전에 없으면 이름만으로 새 속성을 만들고 바로 값을 넣는다 (키는 자동).
 * - Enter 또는 칸 밖을 누르면 저장, Esc는 취소. 저장한 행은 잠깐 강조한다.
 * 같은 속성에 기본값과 옵션값을 각각 넣을 수 있다 (값 옆 "+ 값").
 */

const EMPTY: SpecValueInput = { attribute_key: '', value_text: '', is_option: false, note: '', source_page: null, source_note: '' };

type Cell = { kind: 'add'; key: string } | { kind: 'edit'; id: number; key: string };
type NewAttribute = { name: string; category: string; data_type: DataType; unit: string };
type Row = { attribute: SpecAttribute; values: SpecValue[] };

function placeholderFor(attribute: SpecAttribute | undefined): string {
    if (!attribute) return '값';
    if (attribute.data_type === 'number') return attribute.unit ? `숫자 (${attribute.unit})` : '숫자';
    if (attribute.data_type === 'bool') return '예 / 아니오';
    return attribute.description || '값';
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

function sameInput(a: SpecValueInput, b: SpecValueInput): boolean {
    return a.value_text.trim() === b.value_text.trim() && a.is_option === b.is_option && a.note === b.note
        && a.source_page === b.source_page && a.source_note === b.source_note;
}

/** 사전에 없는 속성의 값도 보이도록 값에서 속성 모양을 만든다 */
function attributeFromSpec(s: SpecValue): SpecAttribute {
    return {
        key: s.attribute_key, name: s.attribute_name || s.attribute_key, category: s.category, data_type: s.data_type, unit: s.unit,
        description: '', sort_order: 9999, inheritable: 0, graph_mode: 'value_node', graph_relation_type: null, graph_entity_type: null,
        usage_count: 0, created_at: '', updated_at: '',
    };
}

export function SpecValuesEditor({
    ownerType,
    ownerId,
    title,
    specs,
    attributes,
    meta,
    scope,
    onChanged,
    onAddDefaultAttributes,
    onAttributesChanged,
}: {
    ownerType: OwnerType;
    ownerId: string;
    /** 표 제목 (예: 제품 사양) */
    title: string;
    specs: SpecValue[];
    attributes: SpecAttribute[];
    meta: SpecMeta | null;
    /** 'product' 또는 부품 종류. "빈 속성도 보기"를 이 대상에 맞는 속성으로 추린다 */
    scope: string;
    /** 값이 바뀌었으니 소유자 상세를 다시 불러오라는 신호 */
    onChanged: () => void;
    onAddDefaultAttributes?: () => Promise<void>;
    /** 새 속성을 만든 뒤 속성 사전을 다시 받는다 */
    onAttributesChanged?: () => Promise<void>;
}) {
    const [query, setQuery] = useState('');
    const [showEmpty, setShowEmpty] = useState(false);
    const [cell, setCell] = useState<Cell | null>(null);
    const [draft, setDraft] = useState<SpecValueInput>(EMPTY);
    const [original, setOriginal] = useState<SpecValueInput>(EMPTY);
    const [more, setMore] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [flash, setFlash] = useState<{ key: string; text: string } | null>(null);
    const [creating, setCreating] = useState<NewAttribute | null>(null);
    /** 방금 만든 속성. 사전 목록이 다시 오기 전에도 행을 그린다 */
    const [created, setCreated] = useState<SpecAttribute | null>(null);
    const savingRef = useRef(false);
    const skipBlurRef = useRef(false);

    // 저장 표시는 잠깐만 보인다 (타이머 정리만 하는 효과)
    useEffect(() => {
        if (!flash) return;
        const t = window.setTimeout(() => setFlash(null), 2500);
        return () => window.clearTimeout(t);
    }, [flash]);

    const allAttributes = created && !attributes.some((a) => a.key === created.key) ? [...attributes, created] : attributes;
    const attributeByKey = new Map(allAttributes.map((a) => [a.key, a]));
    const orderOf = new Map(allAttributes.map((a, i) => [a.key, i]));
    const categories = meta ? Object.keys(meta.attribute_categories) : [];
    const categoryOrder = (c: string) => { const i = categories.indexOf(c); return i < 0 ? 99 : i; };

    const valuesByKey = new Map<string, SpecValue[]>();
    for (const s of specs) valuesByKey.set(s.attribute_key, [...(valuesByKey.get(s.attribute_key) ?? []), s]);
    for (const list of valuesByKey.values()) list.sort((a, b) => Number(a.is_option) - Number(b.is_option));

    // 보일 속성: 값이 있는 속성 + (빈 속성 보기면 대상 속성 전부) + (찾는 중이면 사전 전체) + 지금 입력 중인 속성
    const q = normalizeName(query.trim());
    const candidates = new Map<string, SpecAttribute>();
    for (const key of valuesByKey.keys()) candidates.set(key, attributeByKey.get(key) ?? attributeFromSpec(valuesByKey.get(key)![0]));
    if (showEmpty) for (const a of attributesFor(allAttributes, scope)) candidates.set(a.key, a);
    if (q) for (const a of allAttributes) candidates.set(a.key, a);
    if (cell && attributeByKey.has(cell.key)) candidates.set(cell.key, attributeByKey.get(cell.key)!);

    const matches = (a: SpecAttribute) => !q
        || normalizeName(a.name).includes(q)
        || normalizeName(a.key).includes(q)
        || (valuesByKey.get(a.key) ?? []).some((v) => normalizeName(v.value_text).includes(q));
    const rows: Row[] = [...candidates.values()]
        .filter((a) => a.key === cell?.key || matches(a))
        .sort((a, b) => categoryOrder(a.category) - categoryOrder(b.category) || (orderOf.get(a.key) ?? 9999) - (orderOf.get(b.key) ?? 9999))
        .map((attribute) => ({ attribute, values: valuesByKey.get(attribute.key) ?? [] }));
    const grouped = new Map<string, Row[]>();
    for (const r of rows) grouped.set(r.attribute.category, [...(grouped.get(r.attribute.category) ?? []), r]);

    const scopedCount = attributesFor(allAttributes, scope).length;
    const emptyCount = attributesFor(allAttributes, scope).filter((a) => !valuesByKey.has(a.key)).length;
    const exact = q ? sameNameAttribute(allAttributes, query) : undefined;

    function startAdd(key: string, asOption = false) {
        if (busy) return;
        skipBlurRef.current = false;
        const start = { ...EMPTY, attribute_key: key, is_option: asOption };
        setCell({ kind: 'add', key });
        setDraft(start);
        setOriginal(start);
        setMore(false);
        setError('');
    }

    function startEdit(spec: SpecValue) {
        if (busy) return;
        skipBlurRef.current = false;
        const start = toInput(spec);
        setCell({ kind: 'edit', id: spec.id, key: spec.attribute_key });
        setDraft(start);
        setOriginal(start);
        setMore(Boolean(spec.note || spec.source_note || spec.source_page));
        setError('');
    }

    function cancel() {
        skipBlurRef.current = true;
        setCell(null);
    }

    async function commit() {
        if (!cell || savingRef.current) return;
        const text = draft.value_text.trim();
        // 비운 채로 나가거나 바꾼 게 없으면 저장하지 않는다 (값 지우기는 휴지통으로)
        if (!text || sameInput(draft, original)) { skipBlurRef.current = true; setCell(null); return; }
        const attribute = attributeByKey.get(cell.key);
        savingRef.current = true;
        setBusy(true);
        setError('');
        try {
            const input = { ...draft, value_text: text };
            if (cell.kind === 'add') await specApi.addValue({ owner_type: ownerType, owner_id: ownerId }, input);
            else await specApi.updateValue(cell.id, input);
            const unit = attribute?.data_type === 'number' && attribute.unit && !text.includes(attribute.unit) ? attribute.unit : '';
            setFlash({ key: cell.key, text: `${attribute?.name ?? cell.key} ${text}${unit}${draft.is_option ? ' (옵션)' : ''} 저장했습니다.` });
            skipBlurRef.current = true;
            setCell(null);
            onChanged();
        } catch (e) {
            setError(errorMessage(e, '사양 값을 저장하지 못했습니다.'));
        } finally {
            savingRef.current = false;
            setBusy(false);
        }
    }

    async function remove(spec: SpecValue) {
        if (busy || !window.confirm(`'${spec.attribute_name} = ${spec.value_text}' 값을 삭제할까요?`)) return;
        setBusy(true);
        setError('');
        try {
            await specApi.deleteValue(spec.id);
            setFlash({ key: spec.attribute_key, text: `${spec.attribute_name} ${spec.value_text} 값을 지웠습니다.` });
            onChanged();
        } catch (e) {
            setError(errorMessage(e, '사양 값을 삭제하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    function startCreate() {
        setCreating({ name: query.trim(), category: defaultCategoryFor(scope), data_type: 'text', unit: '' });
        setError('');
    }

    async function createAttribute() {
        if (!creating) return;
        const name = creating.name.trim();
        if (!name || sameNameAttribute(allAttributes, name)) return;
        setBusy(true);
        setError('');
        try {
            const saved = await specApi.createAttribute({
                key: autoAttributeKey(name, allAttributes.map((a) => a.key)),
                name,
                category: creating.category,
                data_type: creating.data_type,
                unit: creating.data_type === 'number' ? creating.unit.trim() : '',
                description: '',
                sort_order: nextSortOrder(allAttributes, creating.category),
            });
            setCreated(saved);
            setCreating(null);
            setQuery(saved.name);
            await onAttributesChanged?.();
            setBusy(false);
            startAdd(saved.key);
        } catch (e) {
            setError(errorMessage(e, '속성을 만들지 못했습니다.'));
            setBusy(false);
        }
    }

    function onSearchKey(e: KeyboardEvent<HTMLInputElement>) {
        if (e.key === 'Escape') { setQuery(''); return; }
        if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
        e.preventDefault();
        // 하나만 남으면 바로 입력, 없으면 새 속성 만들기
        if (rows.length === 1) {
            const only = rows[0];
            if (only.values.length === 0) startAdd(only.attribute.key);
            else startEdit(only.values[0]);
        } else if (rows.length === 0 && q && !exact) {
            startCreate();
        }
    }

    if (attributes.length === 0) {
        return (
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 text-[12.5px]">
                <span className="text-muted">속성 사전이 비어 있어 값을 넣을 수 없습니다. 기본 속성을 먼저 추가하세요.</span>
                {onAddDefaultAttributes && <button type="button" onClick={() => void onAddDefaultAttributes()} className={btnPrimary}>기본 속성 추가</button>}
            </div>
        );
    }

    const editorProps = {
        draft, more, busy,
        onChange: (patch: Partial<SpecValueInput>) => setDraft((d) => ({ ...d, ...patch })),
        onToggleMore: () => setMore((v) => !v),
        onCommit: () => void commit(),
        onCancel: cancel,
        onBlurOut: () => { if (skipBlurRef.current) { skipBlurRef.current = false; return; } void commit(); },
    };

    return (
        <div>
            {/* 도구줄: 제목, 찾기, 빈 속성 보기, 저장 표시 */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-divide px-5 py-3">
                <h3 className="text-[14px] font-bold">{title} <span className="font-semibold text-muted tabular-nums">{specs.length}</span></h3>
                <div className="relative w-full sm:w-[260px]">
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => { setQuery(e.target.value); setCreating(null); }}
                        onKeyDown={onSearchKey}
                        placeholder="속성·값 찾기 (예: 무게)"
                        aria-label="속성·값 찾기"
                        className={`${smallInputCls} pr-7`}
                    />
                    {query && (
                        <button type="button" onClick={() => setQuery('')} aria-label="찾기 지우기" className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex h-5 w-5 items-center justify-center rounded text-muted hover:text-ink">
                            <CloseIcon />
                        </button>
                    )}
                </div>
                <label className="inline-flex items-center gap-1.5 text-[12px] text-muted">
                    <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} className="accent-brand" />
                    빈 속성도 보기 <span className="tabular-nums">({emptyCount}/{scopedCount})</span>
                </label>
                <p role="status" aria-live="polite" className="ml-auto text-[12px] font-semibold text-brand-hover">{flash?.text}</p>
            </div>

            {error && <div className="px-5 pt-3"><Notice kind="error">{error}</Notice></div>}

            {rows.length > 0 && (
                <table className="w-full text-[12.5px]">
                    <tbody>
                        {[...grouped.entries()].map(([category, list]) => (
                            <GroupRows
                                key={category}
                                title={labelOf(meta?.attribute_categories, category)}
                                rows={list}
                                cell={cell}
                                flashKey={flash?.key ?? null}
                                busy={busy}
                                editorProps={editorProps}
                                onStartAdd={startAdd}
                                onStartEdit={startEdit}
                                onRemove={(s) => void remove(s)}
                            />
                        ))}
                    </tbody>
                </table>
            )}

            {rows.length === 0 && !q && (
                <p className="px-5 py-6 text-[12.5px] leading-6 text-muted">
                    아직 넣은 사양이 없습니다. 위 <b className="text-ink">속성·값 찾기</b>에 속성 이름을 치거나 <b className="text-ink">빈 속성도 보기</b>를 켜고, 값 칸을 눌러 바로 입력하세요.
                </p>
            )}
            {rows.length === 0 && q && (
                <p className="px-5 pt-5 text-[12.5px] text-muted">'{query.trim()}'에 맞는 속성이나 값이 없습니다.</p>
            )}

            {/* 찾는 속성이 사전에 없으면 이름만으로 만든다 */}
            {q && !exact && (
                <div className="px-5 py-4">
                    {creating ? (
                        <NewAttributeForm
                            value={creating}
                            meta={meta}
                            busy={busy}
                            duplicate={sameNameAttribute(allAttributes, creating.name)}
                            onChange={(patch) => setCreating((c) => (c ? { ...c, ...patch } : c))}
                            onUseExisting={(a) => { setCreating(null); setQuery(a.name); }}
                            onSubmit={() => void createAttribute()}
                            onCancel={() => setCreating(null)}
                        />
                    ) : (
                        <button type="button" onClick={startCreate} disabled={busy} className="text-[12.5px] font-semibold text-brand hover:text-brand-hover disabled:opacity-40">
                            + '{query.trim()}' 새 속성으로 만들기
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}

interface EditorProps {
    draft: SpecValueInput;
    more: boolean;
    busy: boolean;
    onChange: (patch: Partial<SpecValueInput>) => void;
    onToggleMore: () => void;
    onCommit: () => void;
    onCancel: () => void;
    onBlurOut: () => void;
}

function GroupRows({
    title,
    rows,
    cell,
    flashKey,
    busy,
    editorProps,
    onStartAdd,
    onStartEdit,
    onRemove,
}: {
    title: string;
    rows: Row[];
    cell: Cell | null;
    flashKey: string | null;
    busy: boolean;
    editorProps: EditorProps;
    onStartAdd: (key: string, asOption?: boolean) => void;
    onStartEdit: (s: SpecValue) => void;
    onRemove: (s: SpecValue) => void;
}) {
    return (
        <>
            <tr>
                <td colSpan={2} className="px-5 pt-4 pb-1 text-[11px] font-bold text-muted">{title}</td>
            </tr>
            {rows.map(({ attribute: a, values }) => {
                const adding = cell?.kind === 'add' && cell.key === a.key;
                return (
                    <tr key={a.key} className={`group/row border-t border-divide align-top transition-colors duration-700 ${flashKey === a.key ? 'bg-brand-soft/60' : 'hover:bg-surface'}`}>
                        <td className="w-[34%] max-w-[260px] py-2 pl-5 pr-3" title={a.description || undefined}>
                            <span className="font-semibold">{a.name}</span>
                            {a.unit && <span className="ml-1 text-muted">({a.unit})</span>}
                        </td>
                        <td className="py-1.5 pr-5">
                            <div className="flex flex-col gap-1">
                                {values.map((s, i) => (
                                    cell?.kind === 'edit' && cell.id === s.id ? (
                                        <ValueEditor key={s.id} attribute={a} {...editorProps} />
                                    ) : (
                                        <div key={s.id} className="flex items-start gap-1">
                                            <button
                                                type="button"
                                                onClick={() => onStartEdit(s)}
                                                disabled={busy}
                                                title="눌러서 고치기"
                                                className="min-w-0 flex-1 rounded-md px-2 py-0.5 -mx-2 text-left hover:bg-chip disabled:cursor-default"
                                            >
                                                <span className="tabular-nums break-words">{s.value_text}</span>
                                                {s.data_type === 'number' && s.unit && !s.value_text.includes(s.unit) && <span className="ml-1 text-muted">{s.unit}</span>}
                                                {s.is_option && <span className="ml-1.5 align-middle"><Pill tone="warn">옵션</Pill></span>}
                                                {(s.note || s.source_note || s.source_page) && (
                                                    <span className="block text-[11px] text-muted">
                                                        {[s.note, [s.source_note, s.source_page ? `${s.source_page}쪽` : ''].filter(Boolean).join(' ')].filter(Boolean).join(' · ')}
                                                    </span>
                                                )}
                                            </button>
                                            {i === values.length - 1 && !adding && (
                                                <button
                                                    type="button"
                                                    onClick={() => onStartAdd(a.key, true)}
                                                    disabled={busy}
                                                    title="같은 속성에 값 하나 더 (옵션 구성 등)"
                                                    className={`${btnTiny} whitespace-nowrap opacity-0 group-hover/row:opacity-100 focus:opacity-100 hover:text-brand`}
                                                >
                                                    + 값
                                                </button>
                                            )}
                                            <button
                                                type="button"
                                                onClick={() => onRemove(s)}
                                                disabled={busy}
                                                aria-label={`${a.name} ${s.value_text} 삭제`}
                                                title="삭제"
                                                className={`${btnTiny} opacity-0 group-hover/row:opacity-100 focus:opacity-100 hover:text-danger`}
                                            >
                                                <TrashIcon />
                                            </button>
                                        </div>
                                    )
                                ))}
                                {adding ? (
                                    <ValueEditor attribute={a} {...editorProps} />
                                ) : values.length === 0 && (
                                    <button
                                        type="button"
                                        onClick={() => onStartAdd(a.key)}
                                        disabled={busy}
                                        className="w-full rounded-md px-2 py-0.5 -mx-2 text-left text-muted/80 hover:bg-chip hover:text-brand disabled:cursor-default"
                                    >
                                        + 입력
                                    </button>
                                )}
                            </div>
                        </td>
                    </tr>
                );
            })}
        </>
    );
}

/** 값 칸 안의 입력. Enter·칸 밖 클릭 = 저장, Esc = 취소. 옵션·비고·출처는 "비고·출처"를 눌러 연다 */
function ValueEditor({ attribute, draft, more, busy, onChange, onToggleMore, onCommit, onCancel, onBlurOut }: EditorProps & { attribute: SpecAttribute }) {
    const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Escape') { e.preventDefault(); onCancel(); return; }
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); onCommit(); }
    };
    return (
        <div
            className="flex flex-col gap-1.5 py-0.5"
            onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onBlurOut(); }}
        >
            <div className="flex flex-wrap items-center gap-2">
                <input
                    autoFocus
                    value={draft.value_text}
                    onChange={(e) => onChange({ value_text: e.target.value })}
                    onKeyDown={onKey}
                    disabled={busy}
                    placeholder={placeholderFor(attribute)}
                    aria-label={`${attribute.name} 값`}
                    className={`${smallInputCls} max-w-[360px] flex-1 min-w-[160px]`}
                />
                <label className="inline-flex items-center gap-1 text-[11.5px] text-muted">
                    <input type="checkbox" checked={draft.is_option} onChange={(e) => onChange({ is_option: e.target.checked })} disabled={busy} className="accent-brand" />
                    옵션
                </label>
                <button type="button" onClick={onToggleMore} className={btnTiny}>{more ? '비고·출처 닫기' : '비고·출처'}</button>
                <span className="text-[11px] text-muted">{busy ? '저장 중…' : 'Enter 저장 · Esc 취소'}</span>
            </div>
            {more && (
                <div className="grid max-w-[560px] grid-cols-[minmax(0,1fr)_64px_minmax(0,1fr)] gap-1.5">
                    <input value={draft.note} onChange={(e) => onChange({ note: e.target.value })} onKeyDown={onKey} disabled={busy} placeholder="비고 (예: 공유 메모리)" aria-label="비고" className={smallInputCls} />
                    <input
                        type="number"
                        min={1}
                        value={draft.source_page ?? ''}
                        onChange={(e) => onChange({ source_page: e.target.value ? Number(e.target.value) : null })}
                        onKeyDown={onKey}
                        disabled={busy}
                        placeholder="쪽"
                        aria-label="근거 페이지"
                        className={smallInputCls}
                    />
                    <input value={draft.source_note} onChange={(e) => onChange({ source_note: e.target.value })} onKeyDown={onKey} disabled={busy} placeholder="출처 (예: Sales Guide V1.3)" aria-label="출처 메모" className={smallInputCls} />
                </div>
            )}
        </div>
    );
}

/** 사전에 없는 속성을 이름만으로 만든다. 키는 자동, 분류 끝에 붙는다. 같은 이름이 있으면 그걸 쓰게 한다 */
function NewAttributeForm({ value, meta, busy, duplicate, onChange, onUseExisting, onSubmit, onCancel }: {
    value: NewAttribute;
    meta: SpecMeta | null;
    busy: boolean;
    duplicate: SpecAttribute | undefined;
    onChange: (patch: Partial<NewAttribute>) => void;
    onUseExisting: (a: SpecAttribute) => void;
    onSubmit: () => void;
    onCancel: () => void;
}) {
    const canSubmit = !busy && value.name.trim().length > 0 && !duplicate;
    return (
        <form
            onSubmit={(e) => { e.preventDefault(); if (canSubmit) onSubmit(); }}
            className="flex flex-col gap-2"
            aria-label="새 속성"
        >
            <p className="text-[12px] font-semibold">새 속성</p>
            <div className="flex flex-wrap items-center gap-2">
                <input autoFocus value={value.name} onChange={(e) => onChange({ name: e.target.value })} placeholder="이름 (예: 팬 개수)" aria-label="새 속성 이름" className={`${smallInputCls} !w-[200px]`} />
                <select value={value.category} onChange={(e) => onChange({ category: e.target.value })} aria-label="분류" className={`${smallInputCls} !w-[130px]`}>
                    {Object.entries(meta?.attribute_categories ?? { other: '기타' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <select value={value.data_type} onChange={(e) => onChange({ data_type: e.target.value as DataType })} aria-label="값 종류" className={`${smallInputCls} !w-[110px]`}>
                    <option value="text">글자</option>
                    <option value="number">숫자</option>
                    <option value="bool">예/아니오</option>
                </select>
                {value.data_type === 'number' && (
                    <input value={value.unit} onChange={(e) => onChange({ unit: e.target.value })} placeholder="단위 (예: kg)" aria-label="단위" className={`${smallInputCls} !w-[100px]`} />
                )}
                <button type="submit" disabled={!canSubmit} className={`${btnPrimary} !h-8`}>{busy ? '만드는 중…' : '만들고 값 입력'}</button>
                <button type="button" onClick={onCancel} className={btnTiny}>취소</button>
            </div>
            {duplicate ? (
                <p className="text-[11.5px] text-warn">
                    이미 '{duplicate.name}' 속성이 있습니다.
                    <button type="button" onClick={() => onUseExisting(duplicate)} className={`${btnTiny} ml-1 text-brand`}>그 속성에 입력</button>
                </p>
            ) : (
                <p className="text-[11px] text-muted">숫자로 고르면 입찰 조건의 "이상·이하" 비교에 쓰입니다. 그 밖의 설정은 속성 탭에서 바꿉니다.</p>
            )}
        </form>
    );
}
