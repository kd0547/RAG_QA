import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronIcon, TrashIcon } from '../components/icons';
import { specApi, type Component, type Product, type ProductDetail, type ProductInput, type SpecAttribute, type SpecMeta } from './api';
import { SpecValuesEditor } from './SpecValuesEditor';
import { btnDanger, btnGhost, btnPrimary, btnTiny, errorMessage, formatDate, inputCls, labelOf, selectCls, smallInputCls } from './styles';
import { Card, Field, ListItem, Notice, Pill } from './ui';

const EMPTY: ProductInput = { model: '', name: '', category: 'notebook', status: 'active', note: '', parent_id: null };
type ActiveId = string | 'new' | null;
type TreeRow = { product: Product; depth: number };

function toInput(p: ProductDetail): ProductInput {
    return { model: p.model, name: p.name, category: p.category, status: p.status, note: p.note, parent_id: p.parent_id };
}

/** 상위 모델 id → 바로 아래 하위 모델 목록. 상위가 목록에 없으면 최상위(null)로 둔다 */
function groupByParent(products: Product[]): Map<string | null, Product[]> {
    const ids = new Set(products.map((p) => p.id));
    const map = new Map<string | null, Product[]>();
    for (const p of products) {
        const key = p.parent_id && ids.has(p.parent_id) ? p.parent_id : null;
        map.set(key, [...(map.get(key) ?? []), p]);
    }
    return map;
}

/** rootId 아래 트리를 위에서부터 펼친 순서. open을 주면 펼친 모델의 하위만 넣는다 */
function flattenTree(byParent: Map<string | null, Product[]>, rootId: string | null, open?: Set<string>): TreeRow[] {
    const rows: TreeRow[] = [];
    const walk = (parentId: string | null, depth: number) => {
        for (const product of byParent.get(parentId) ?? []) {
            rows.push({ product, depth });
            if (!open || open.has(product.id)) walk(product.id, depth + 1);
        }
    };
    walk(rootId, 0);
    return rows;
}

/** 제품 탭: 왼쪽 제품 트리(모델 → 하위 모델), 오른쪽에 제품 정보·제품 사양·구성 부품·하위 모델 */
export function ProductsTab({
    meta,
    attributes,
    components,
    onAddDefaultAttributes,
    onComponentsChanged,
}: {
    meta: SpecMeta | null;
    attributes: SpecAttribute[];
    components: Component[];
    onAddDefaultAttributes: () => Promise<void>;
    /** 부품 연결이 바뀌면 부품 목록의 사용 수가 바뀌므로 알린다 */
    onComponentsChanged: () => void;
}) {
    const [products, setProducts] = useState<Product[] | null>(null);
    const [loadError, setLoadError] = useState('');
    const [activeId, setActiveId] = useState<ActiveId>(null);
    const [detail, setDetail] = useState<ProductDetail | null>(null);
    const [detailKey, setDetailKey] = useState(0);
    const [draft, setDraft] = useState<ProductInput>(EMPTY);
    /** 새 제품 폼의 처음 값. 하위 모델 추가는 상위 모델 값을 채워 시작한다 */
    const [newBase, setNewBase] = useState<ProductInput>(EMPTY);
    /** 왼쪽 트리에서 하위 모델을 펼친 제품 */
    const [open, setOpen] = useState<Set<string>>(() => new Set());
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const [link, setLink] = useState({ component_id: '', is_option: false, note: '' });

    const loadList = useCallback(async () => {
        try {
            const list = await specApi.listProducts();
            setProducts(list);
            setLoadError('');
            return list;
        } catch (e) {
            setLoadError(errorMessage(e, '제품 목록을 불러오지 못했습니다.'));
            return null;
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        specApi.listProducts()
            .then((list) => {
                if (cancelled) return;
                setProducts(list);
                setActiveId(list[0]?.id ?? null);
            })
            .catch((e) => { if (!cancelled) setLoadError(errorMessage(e, '제품 목록을 불러오지 못했습니다.')); });
        return () => { cancelled = true; };
    }, []);

    // 선택한 제품의 상세. detailKey가 바뀌면 다시 받는다 (사양 값·부품 변경 후)
    useEffect(() => {
        if (!activeId || activeId === 'new') return;
        let cancelled = false;
        specApi.getProduct(activeId)
            .then((d) => {
                if (cancelled) return;
                setDetail(d);
                setDraft(toInput(d));
            })
            .catch((e) => { if (!cancelled) setError(errorMessage(e, '제품 정보를 불러오지 못했습니다.')); });
        return () => { cancelled = true; };
    }, [activeId, detailKey]);

    const isNew = activeId === 'new';
    const base = isNew ? newBase : detail ? toInput(detail) : EMPTY;
    const dirty = (Object.keys(EMPTY) as (keyof ProductInput)[]).some((k) => draft[k] !== base[k]);
    const canSave = !busy && draft.model.trim().length > 0 && (isNew || dirty);

    const byId = useMemo(() => new Map((products ?? []).map((p) => [p.id, p])), [products]);
    const byParent = useMemo(() => groupByParent(products ?? []), [products]);
    const treeRows = flattenTree(byParent, null, open);
    const hasTree = (products ?? []).some((p) => p.parent_id && byId.has(p.parent_id));

    /** 최상위 모델부터 id까지의 경로 (id 포함) */
    function pathTo(id: string | null): Product[] {
        const path: Product[] = [];
        for (let p = id ? byId.get(id) : undefined; p && path.length < 20; p = p.parent_id ? byId.get(p.parent_id) : undefined) {
            path.unshift(p);
        }
        return path;
    }

    /** 트리에서 id가 보이도록 상위 모델들을 펼친다 */
    function reveal(ancestorIds: string[]) {
        if (ancestorIds.length === 0) return;
        setOpen((prev) => new Set([...prev, ...ancestorIds]));
    }

    function toggleOpen(id: string) {
        setOpen((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }

    function clear() { setNotice(''); setError(''); }

    function confirmLeave() {
        return !dirty || window.confirm('저장하지 않은 변경 사항이 있습니다. 버리고 이동할까요?');
    }

    function switchTo(id: string | null) {
        if (id === activeId || !confirmLeave()) return;
        clear();
        setActiveId(id);
        reveal(pathTo(id).slice(0, -1).map((p) => p.id));
    }

    /** 새 제품 폼을 연다. parent가 있으면 그 모델의 하위 모델로 시작한다 */
    function startNew(parent?: ProductDetail) {
        if (isNew && newBase.parent_id === (parent?.id ?? null)) return;
        if (!confirmLeave()) return;
        const start: ProductInput = parent
            ? { ...EMPTY, model: `${parent.model}-`, category: parent.category, status: parent.status, parent_id: parent.id }
            : EMPTY;
        clear();
        setActiveId('new');
        setDetail(null);
        setNewBase(start);
        setDraft(start);
    }

    const refreshDetail = () => { setDetailKey((k) => k + 1); void loadList(); };

    async function save() {
        if (!canSave) return;
        setBusy(true);
        clear();
        try {
            const saved = isNew || !detail ? await specApi.createProduct(draft) : await specApi.updateProduct(detail.id, draft);
            await loadList();
            setDetail(saved);
            setDraft(toInput(saved));
            setActiveId(saved.id);
            reveal(saved.ancestors.map((a) => a.id));
            setNotice(isNew ? `'${saved.model}' ${saved.parent_id ? '하위 모델' : '제품'}을 등록했습니다. 아래에서 사양과 부품을 넣으세요.` : '저장했습니다.');
        } catch (e) {
            setError(errorMessage(e, '저장하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    async function remove() {
        if (!detail || isNew || busy) return;
        if (!window.confirm(`'${detail.model}' 제품을 삭제할까요?\n제품 사양과 부품 연결도 함께 지워집니다.`)) return;
        setBusy(true);
        clear();
        try {
            await specApi.deleteProduct(detail.id);
            const list = await loadList();
            setDetail(null);
            setActiveId(detail.parent_id ?? list?.[0]?.id ?? null);
            setNotice(`'${detail.model}' 제품을 삭제했습니다.`);
            onComponentsChanged();
        } catch (e) {
            setError(errorMessage(e, '삭제하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    async function addLink() {
        if (!detail || !link.component_id) return;
        setBusy(true);
        clear();
        try {
            const updated = await specApi.linkComponent(detail.id, link);
            setDetail(updated);
            setLink({ component_id: '', is_option: false, note: '' });
            void loadList();
            onComponentsChanged();
        } catch (e) {
            setError(errorMessage(e, '부품을 연결하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    async function toggleLinkOption(componentId: string, isOption: boolean, note: string) {
        if (!detail) return;
        setBusy(true);
        clear();
        try {
            setDetail(await specApi.linkComponent(detail.id, { component_id: componentId, is_option: isOption, note }));
        } catch (e) {
            setError(errorMessage(e, '부품 구성을 바꾸지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    async function removeLink(componentId: string, model: string) {
        if (!detail || !window.confirm(`'${model}' 부품을 이 제품에서 뺄까요? 부품 자체는 남습니다.`)) return;
        setBusy(true);
        clear();
        try {
            setDetail(await specApi.unlinkComponent(detail.id, componentId));
            void loadList();
            onComponentsChanged();
        } catch (e) {
            setError(errorMessage(e, '부품을 빼지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    // 위치 표시: 저장된 제품은 서버가 준 상위 경로, 새 제품은 고른 상위 모델까지의 경로
    const crumbs = isNew ? pathTo(draft.parent_id) : detail?.ancestors ?? [];
    // 상위 모델 후보: 자기 자신과 자기 하위 모델은 뺀다
    const blocked = new Set<string>();
    if (!isNew && detail) {
        blocked.add(detail.id);
        for (const { product } of flattenTree(byParent, detail.id)) blocked.add(product.id);
    }
    const parentOptions = flattenTree(byParent, null).filter(({ product }) => !blocked.has(product.id));

    const linkedIds = new Set(detail?.components.map((c) => c.id) ?? []);
    const kinds = meta ? Object.keys(meta.component_kinds) : [];
    const kindOrder = (k: string) => { const i = kinds.indexOf(k); return i < 0 ? 99 : i; };
    const availableByKind = new Map<string, Component[]>();
    for (const c of components.filter((c) => !linkedIds.has(c.id))) {
        availableByKind.set(c.kind, [...(availableByKind.get(c.kind) ?? []), c]);
    }

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[260px] lg:w-[290px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                <h1 className="text-[16px] font-bold">제품</h1>
                <p className="mt-1 text-[12px] leading-5 text-muted">입찰 조건과 대조할 우리 제품입니다. 모델 아래에 하위 모델(파생 모델)을 두고, 모델마다 사양과 부품을 등록합니다.</p>
                <button
                    type="button"
                    onClick={() => startNew()}
                    disabled={products === null}
                    aria-pressed={isNew && !draft.parent_id}
                    className={`mt-4 w-full h-9 rounded-lg border text-[12px] font-semibold transition-colors disabled:opacity-40 ${isNew && !draft.parent_id ? 'border-brand/25 bg-brand-tint text-brand-hover' : 'border-line hover:bg-chip'}`}
                >
                    + 새 제품
                </button>
                <nav aria-label="제품 목록" className="mt-3 flex md:flex-col gap-1.5 overflow-x-auto md:overflow-visible">
                    {products === null && !loadError && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                    {loadError && <Notice kind="error">{loadError}</Notice>}
                    {products?.length === 0 && <p className="text-[12px] text-muted px-1 py-2">아직 등록된 제품이 없습니다.</p>}
                    {treeRows.map(({ product: p, depth }) => {
                        const hasChildren = (byParent.get(p.id)?.length ?? 0) > 0;
                        const expanded = open.has(p.id);
                        return (
                            <div key={p.id} className="shrink-0 min-w-[200px] md:min-w-0 flex items-center gap-0.5" style={{ paddingLeft: depth * 14 }}>
                                {hasChildren ? (
                                    <button
                                        type="button"
                                        onClick={() => toggleOpen(p.id)}
                                        aria-expanded={expanded}
                                        aria-label={`${p.model} 하위 모델 ${expanded ? '접기' : '펼치기'}`}
                                        className="w-5 h-7 shrink-0 inline-flex items-center justify-center rounded text-muted hover:text-ink hover:bg-chip"
                                    >
                                        <ChevronIcon className={`w-2 h-2 transition-transform ${expanded ? '' : '-rotate-90'}`} />
                                    </button>
                                ) : (
                                    hasTree && <span className="w-5 shrink-0" aria-hidden />
                                )}
                                <div className="min-w-0 flex-1">
                                    <ListItem
                                        active={activeId === p.id}
                                        title={p.model}
                                        subtitle={p.name || undefined}
                                        badge={p.status !== 'active' ? <Pill tone={p.status === 'eol' ? 'muted' : 'warn'}>{labelOf(meta?.product_statuses, p.status)}</Pill> : undefined}
                                        onClick={() => switchTo(p.id)}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </nav>
            </aside>

            <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8">
                <div className="mx-auto max-w-[960px] flex flex-col gap-5">
                    {activeId === null ? (
                        <p className="text-[13px] text-muted">왼쪽에서 제품을 고르거나 새 제품을 등록하세요.</p>
                    ) : (
                        <>
                            <div>
                                {crumbs.length > 0 && (
                                    <nav aria-label="상위 모델" className="mb-1 flex flex-wrap items-center gap-1 text-[12px] text-muted">
                                        {crumbs.map((c) => (
                                            <span key={c.id} className="inline-flex items-center gap-1">
                                                <button type="button" onClick={() => switchTo(c.id)} className="font-semibold hover:text-ink hover:underline">{c.model}</button>
                                                <span aria-hidden>›</span>
                                            </span>
                                        ))}
                                    </nav>
                                )}
                                <div className="flex flex-wrap items-center gap-2">
                                    <h2 className="text-[22px] font-bold tracking-tight break-all">{isNew ? (draft.parent_id ? '새 하위 모델' : '새 제품') : detail?.model ?? '…'}</h2>
                                    {detail && !isNew && <Pill tone={detail.status === 'active' ? 'brand' : 'muted'}>{labelOf(meta?.product_statuses, detail.status)}</Pill>}
                                </div>
                                <p className="mt-1.5 text-[12.5px] text-muted">
                                    {isNew ? '모델명을 입력해 저장하면 사양과 부품을 넣을 수 있습니다.' : detail ? `${formatDate(detail.updated_at)} 저장` : ''}
                                </p>
                            </div>

                            {notice && <Notice kind="ok">{notice}</Notice>}
                            {error && <Notice kind="error">{error}</Notice>}

                            <Card
                                title="제품 정보"
                                aside={
                                    <div className="flex items-center gap-2">
                                        {!isNew && detail && (
                                            <button
                                                type="button"
                                                onClick={() => void remove()}
                                                disabled={busy || detail.children.length > 0}
                                                title={detail.children.length > 0 ? '하위 모델이 있어 지울 수 없습니다. 하위 모델을 먼저 지우거나 옮기세요.' : undefined}
                                                className={btnDanger}
                                            >
                                                <TrashIcon />삭제
                                            </button>
                                        )}
                                        <button type="button" onClick={() => void save()} disabled={!canSave} className={btnPrimary}>
                                            {busy ? '저장 중…' : isNew ? '등록' : '저장'}
                                        </button>
                                    </div>
                                }
                            >
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <Field label="모델명" htmlFor="product-model" hint="입찰 답변과 검색에 쓰는 기준 이름. 예: N5800, N5800-GB70-PU02">
                                        <input id="product-model" value={draft.model} onChange={(e) => { setDraft((d) => ({ ...d, model: e.target.value })); clear(); }} maxLength={50} placeholder="N5800" className={inputCls} />
                                    </Field>
                                    <Field label="제품 이름" htmlFor="product-name" hint="세대나 설명을 붙인 표시 이름">
                                        <input id="product-name" value={draft.name} onChange={(e) => { setDraft((d) => ({ ...d, name: e.target.value })); clear(); }} maxLength={100} placeholder="N5800 14세대 노트북" className={inputCls} />
                                    </Field>
                                    <Field label="제품 종류" htmlFor="product-category">
                                        <select id="product-category" value={draft.category} onChange={(e) => { setDraft((d) => ({ ...d, category: e.target.value })); clear(); }} className={selectCls}>
                                            {Object.entries(meta?.product_categories ?? { notebook: '노트북' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="상태" htmlFor="product-status">
                                        <select id="product-status" value={draft.status} onChange={(e) => { setDraft((d) => ({ ...d, status: e.target.value })); clear(); }} className={selectCls}>
                                            {Object.entries(meta?.product_statuses ?? { active: '판매 중' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="상위 모델" htmlFor="product-parent" className="sm:col-span-2" hint="파생 모델이면 갈라져 나온 모델을 고릅니다. 비우면 최상위 모델입니다.">
                                        <select id="product-parent" value={draft.parent_id ?? ''} onChange={(e) => { setDraft((d) => ({ ...d, parent_id: e.target.value || null })); clear(); }} className={selectCls}>
                                            <option value="">없음 (최상위 모델)</option>
                                            {parentOptions.map(({ product: p, depth }) => (
                                                <option key={p.id} value={p.id}>{'\u00a0\u00a0'.repeat(depth)}{p.model}{p.name ? ` · ${p.name}` : ''}</option>
                                            ))}
                                        </select>
                                    </Field>
                                    <Field label="비고" htmlFor="product-note" className="sm:col-span-2">
                                        <input id="product-note" value={draft.note} onChange={(e) => { setDraft((d) => ({ ...d, note: e.target.value })); clear(); }} maxLength={500} placeholder="예: 공공 입찰 주력 모델" className={inputCls} />
                                    </Field>
                                </div>
                            </Card>

                            {!isNew && detail && (
                                <>
                                    <Card title="제품 사양">
                                        <SpecValuesEditor
                                            ownerType="product"
                                            ownerId={detail.id}
                                            specs={detail.specs}
                                            attributes={attributes}
                                            meta={meta}
                                            scope="product"
                                            onChanged={refreshDetail}
                                            onAddDefaultAttributes={onAddDefaultAttributes}
                                        />
                                    </Card>

                                    <Card title="구성 부품">
                                        {detail.components.length === 0 ? (
                                            <p className="text-[12.5px] text-muted py-1">연결된 부품이 없습니다. CPU, GPU, SSD처럼 코어 수·클럭 등 세부 값이 부품 쪽에 있는 항목을 연결하세요.</p>
                                        ) : (
                                            <table className="w-full text-[12.5px]">
                                                <thead>
                                                    <tr className="text-left text-[11px] text-muted">
                                                        <th className="py-1.5 pr-3 font-semibold">종류</th>
                                                        <th className="py-1.5 pr-3 font-semibold">모델</th>
                                                        <th className="py-1.5 pr-3 font-semibold">구성</th>
                                                        <th className="py-1.5 pr-3 font-semibold">비고</th>
                                                        <th className="py-1.5 w-[48px]" />
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {detail.components.map((c) => (
                                                        <tr key={c.id} className="border-t border-divide">
                                                            <td className="py-2 pr-3 text-muted">{labelOf(meta?.component_kinds, c.kind)}</td>
                                                            <td className="py-2 pr-3 font-semibold">{c.model}{c.vendor && <span className="ml-1.5 font-normal text-muted">{c.vendor}</span>}</td>
                                                            <td className="py-2 pr-3">
                                                                <button
                                                                    type="button"
                                                                    onClick={() => void toggleLinkOption(c.id, !c.is_option, c.link_note)}
                                                                    disabled={busy}
                                                                    title="눌러서 기본 구성 / 옵션 구성 전환"
                                                                    className="disabled:opacity-40"
                                                                >
                                                                    <Pill tone={c.is_option ? 'warn' : 'brand'}>{c.is_option ? '옵션' : '기본'}</Pill>
                                                                </button>
                                                            </td>
                                                            <td className="py-2 pr-3 text-muted">{c.link_note || '—'}</td>
                                                            <td className="py-1.5 text-right">
                                                                <button type="button" onClick={() => void removeLink(c.id, c.model)} disabled={busy} aria-label="제품에서 빼기" title="제품에서 빼기" className={`${btnTiny} hover:text-danger`}><TrashIcon /></button>
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        )}

                                        <div className="mt-4 rounded-xl border border-dashed border-line bg-surface px-3 py-3">
                                            <p className="text-[11.5px] font-semibold text-muted">부품 연결</p>
                                            {components.length === 0 ? (
                                                <p className="mt-1.5 text-[12.5px] text-muted">등록된 부품이 없습니다. 부품 탭에서 먼저 등록하세요.</p>
                                            ) : (
                                                <div className="mt-2 grid grid-cols-1 sm:grid-cols-[minmax(0,1.6fr)_auto_minmax(0,1fr)_auto] gap-2">
                                                    <select value={link.component_id} onChange={(e) => setLink((l) => ({ ...l, component_id: e.target.value }))} disabled={busy} aria-label="부품" className={smallInputCls}>
                                                        <option value="">부품 선택…</option>
                                                        {[...availableByKind.entries()].sort((a, b) => kindOrder(a[0]) - kindOrder(b[0])).map(([kind, list]) => (
                                                            <optgroup key={kind} label={labelOf(meta?.component_kinds, kind)}>
                                                                {list.map((c) => <option key={c.id} value={c.id}>{c.model}{c.vendor ? ` · ${c.vendor}` : ''}</option>)}
                                                            </optgroup>
                                                        ))}
                                                    </select>
                                                    <label className="inline-flex h-8 items-center gap-1.5 text-[12px] whitespace-nowrap">
                                                        <input type="checkbox" checked={link.is_option} onChange={(e) => setLink((l) => ({ ...l, is_option: e.target.checked }))} disabled={busy} className="accent-brand" />
                                                        옵션 구성
                                                    </label>
                                                    <input value={link.note} onChange={(e) => setLink((l) => ({ ...l, note: e.target.value }))} disabled={busy} placeholder="비고 (예: 상위 모델 전용)" aria-label="비고" className={smallInputCls} />
                                                    <button type="button" onClick={() => void addLink()} disabled={busy || !link.component_id} className={`${btnPrimary} !h-8`}>연결</button>
                                                </div>
                                            )}
                                        </div>
                                    </Card>

                                    <Card
                                        title="하위 모델"
                                        aside={<button type="button" onClick={() => startNew(detail)} disabled={busy} className={btnGhost}>+ 하위 모델 추가</button>}
                                    >
                                        {detail.children.length === 0 ? (
                                            <p className="text-[12.5px] text-muted py-1">등록된 하위 모델이 없습니다. {detail.model}-GB70-PU02처럼 이 모델에서 갈라진 파생 모델을 추가하세요.</p>
                                        ) : (
                                            <ul className="flex flex-col gap-1">
                                                {detail.children.map((c) => (
                                                    <li key={c.id}>
                                                        <button
                                                            type="button"
                                                            onClick={() => switchTo(c.id)}
                                                            className="w-full flex items-center gap-3 rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-chip"
                                                        >
                                                            <span className="font-semibold">{c.model}</span>
                                                            {c.name && <span className="min-w-0 flex-1 truncate text-muted">{c.name}</span>}
                                                            {c.status !== 'active' && <Pill tone={c.status === 'eol' ? 'muted' : 'warn'}>{labelOf(meta?.product_statuses, c.status)}</Pill>}
                                                        </button>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </Card>
                                </>
                            )}

                            {isNew && (
                                <p className="text-[12px] text-muted">
                                    <button type="button" onClick={() => switchTo(draft.parent_id ?? products?.[0]?.id ?? null)} className={btnGhost}>취소</button>
                                </p>
                            )}
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}
