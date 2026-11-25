import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronIcon, CloseIcon, TrashIcon } from '../components/icons';
import { specApi, type Product, type ProductDetail, type ProductInput, type SpecAttribute, type SpecMeta } from './api';
import { CopyProductDialog, type CopyDone } from './CopyProduct';
import { SpecValuesEditor } from './SpecValuesEditor';
import { btnGhost, btnPrimary, btnTiny, errorMessage, formatDate, inputCls, labelOf, normalizeName, selectCls, smallInputCls } from './styles';
import { Field, ListItem, Notice, Pill } from './ui';

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

/**
 * 제품 탭: 왼쪽은 검색칸과 제품 트리(기본으로 모두 펼침), 오른쪽은 제품 머리줄과 사양 표.
 * 제품 정보(모델명·종류·상태·상위 모델)는 [정보 수정]을 눌렀을 때만 펼친다. 고른 제품은 주소(?product=)에 남긴다.
 */
export function ProductsTab({
    meta,
    attributes,
    onAddDefaultAttributes,
    onAttributesChanged,
    onComponentsChanged,
}: {
    meta: SpecMeta | null;
    attributes: SpecAttribute[];
    onAddDefaultAttributes: () => Promise<void>;
    /** 사양 표에서 새 속성을 만들면 속성 사전을 다시 받는다 */
    onAttributesChanged: () => Promise<void>;
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
    /** 왼쪽 트리에서 하위 모델을 펼친 제품. 처음 불러올 때 전부 펼친다 */
    const [open, setOpen] = useState<Set<string>>(() => new Set());
    const [query, setQuery] = useState('');
    const [editOpen, setEditOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const [copying, setCopying] = useState(false);
    const mainRef = useRef<HTMLElement>(null);

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
                // 하위 모델이 있는 모델은 전부 펼쳐 둔다 (파생 모델이 목록에 바로 보이게)
                setOpen(new Set(list.map((p) => p.parent_id).filter((id): id is string => Boolean(id))));
                const requested = new URLSearchParams(window.location.search).get('product');
                setActiveId(list.find((p) => p.id === requested)?.id ?? list[0]?.id ?? null);
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

    // 고른 제품을 주소에 남긴다 (새로고침·다른 탭 다녀오기·링크 공유 때 그대로 연다)
    useEffect(() => {
        if (!activeId || activeId === 'new') return;
        const url = new URL(window.location.href);
        if (url.searchParams.get('product') === activeId) return;
        url.searchParams.set('product', activeId);
        window.history.replaceState(window.history.state, '', url);
    }, [activeId]);

    const isNew = activeId === 'new';
    const base = isNew ? newBase : detail ? toInput(detail) : EMPTY;
    const dirty = (Object.keys(EMPTY) as (keyof ProductInput)[]).some((k) => draft[k] !== base[k]);

    const byId = useMemo(() => new Map((products ?? []).map((p) => [p.id, p])), [products]);
    const byParent = useMemo(() => groupByParent(products ?? []), [products]);
    const hasTree = (products ?? []).some((p) => p.parent_id && byId.has(p.parent_id));

    /** 최상위 모델부터 id까지의 경로 (id 포함) */
    function pathTo(id: string | null): Product[] {
        const path: Product[] = [];
        for (let p = id ? byId.get(id) : undefined; p && path.length < 20; p = p.parent_id ? byId.get(p.parent_id) : undefined) {
            path.unshift(p);
        }
        return path;
    }

    // 찾기: 모델명·이름에 맞는 제품만 평평하게 (상위 경로를 함께 보여준다)
    const q = normalizeName(query.trim());
    const listRows: TreeRow[] = q
        ? (products ?? []).filter((p) => normalizeName(p.model).includes(q) || normalizeName(p.name).includes(q)).map((product) => ({ product, depth: 0 }))
        : flattenTree(byParent, null, open);

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

    function toTop() { mainRef.current?.scrollTo({ top: 0 }); }

    function confirmLeave() {
        return !dirty || window.confirm('저장하지 않은 제품 정보가 있습니다. 버리고 이동할까요?');
    }

    function switchTo(id: string | null) {
        if (id === activeId || !confirmLeave()) return;
        clear();
        setEditOpen(false);
        setActiveId(id);
        reveal(pathTo(id).slice(0, -1).map((p) => p.id));
        toTop();
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
        toTop();
    }

    const refreshDetail = () => { setDetailKey((k) => k + 1); void loadList(); };

    async function save() {
        if (busy) return;
        if (!draft.model.trim()) { setError('모델명을 입력하세요.'); return; }
        setBusy(true);
        clear();
        try {
            const saved = isNew || !detail ? await specApi.createProduct(draft) : await specApi.updateProduct(detail.id, draft);
            await loadList();
            setDetail(saved);
            setDraft(toInput(saved));
            setActiveId(saved.id);
            setEditOpen(false);
            reveal(saved.ancestors.map((a) => a.id));
            setNotice(isNew ? `'${saved.model}' ${saved.parent_id ? '하위 모델' : '제품'}을 등록했습니다. 아래 사양 표에서 값을 넣으세요.` : '제품 정보를 저장했습니다.');
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
            setEditOpen(false);
            setActiveId(detail.parent_id ?? list?.[0]?.id ?? null);
            setNotice(`'${detail.model}' 제품을 삭제했습니다.`);
            onComponentsChanged();
        } catch (e) {
            setError(errorMessage(e, '삭제하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    /** 복사가 끝나면 새 제품을 연다 */
    async function afterCopy({ product, message }: CopyDone) {
        setCopying(false);
        await loadList();
        setDetail(product);
        setDraft(toInput(product));
        setActiveId(product.id);
        setEditOpen(false);
        reveal(product.ancestors.map((a) => a.id));
        setError('');
        setNotice(message);
        onComponentsChanged();
        toTop();
    }

    async function setLinkOption(componentId: string, isOption: boolean, note: string) {
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
    const formOpen = isNew || editOpen;

    const setField = (patch: Partial<ProductInput>) => { setDraft((d) => ({ ...d, ...patch })); clear(); };

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[250px] lg:w-[280px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:overflow-y-auto">
                <div className="flex items-center justify-between gap-2">
                    <h1 className="text-[15px] font-bold">제품 <span className="font-semibold text-muted tabular-nums">{products?.length ?? ''}</span></h1>
                    <button type="button" onClick={() => startNew()} disabled={products === null} className={`${btnTiny} text-brand`}>+ 새 제품</button>
                </div>
                <div className="relative mt-3">
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Escape') setQuery('');
                            if (e.key === 'Enter' && !e.nativeEvent.isComposing && listRows.length > 0) switchTo(listRows[0].product.id);
                        }}
                        placeholder="모델·이름 찾기"
                        aria-label="제품 찾기"
                        className={`${smallInputCls} pr-7`}
                    />
                    {query && (
                        <button type="button" onClick={() => setQuery('')} aria-label="찾기 지우기" className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex h-5 w-5 items-center justify-center rounded text-muted hover:text-ink">
                            <CloseIcon />
                        </button>
                    )}
                </div>
                <nav aria-label="제품 목록" className="mt-2 flex md:flex-col gap-0.5 overflow-x-auto md:overflow-visible">
                    {products === null && !loadError && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                    {loadError && <Notice kind="error">{loadError}</Notice>}
                    {products?.length === 0 && <p className="text-[12px] text-muted px-1 py-2">아직 등록된 제품이 없습니다.</p>}
                    {q && listRows.length === 0 && <p className="text-[12px] text-muted px-1 py-2">'{query.trim()}'에 맞는 제품이 없습니다.</p>}
                    {listRows.map(({ product: p, depth }) => {
                        const hasChildren = (byParent.get(p.id)?.length ?? 0) > 0;
                        const expanded = open.has(p.id);
                        const parentPath = q ? pathTo(p.parent_id).map((a) => a.model).join(' › ') : '';
                        return (
                            <div key={p.id} className="shrink-0 min-w-[200px] md:min-w-0 flex items-center gap-0.5" style={{ paddingLeft: depth * 14 }}>
                                {!q && hasChildren ? (
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
                                    !q && hasTree && <span className="w-5 shrink-0" aria-hidden />
                                )}
                                <div className="min-w-0 flex-1">
                                    <ListItem
                                        active={activeId === p.id}
                                        title={p.model}
                                        subtitle={[parentPath && `${parentPath} ›`, p.name].filter(Boolean).join(' ') || undefined}
                                        badge={p.status !== 'active' ? <Pill tone={p.status === 'eol' ? 'muted' : 'warn'}>{labelOf(meta?.product_statuses, p.status)}</Pill> : undefined}
                                        onClick={() => switchTo(p.id)}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </nav>
            </aside>

            <main ref={mainRef} className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:px-8 sm:py-7">
                <div className="mx-auto max-w-[960px] flex flex-col gap-4">
                    {activeId === null ? (
                        <p className="text-[13px] text-muted">왼쪽에서 제품을 고르거나 새 제품을 등록하세요.</p>
                    ) : (
                        <>
                            {/* 머리줄: 위치, 모델명·상태, 이름·종류, 동작 */}
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
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
                                    {detail && !isNew && (
                                        <p className="mt-1 text-[12.5px] text-muted">
                                            {[detail.name, labelOf(meta?.product_categories, detail.category), detail.note, `${formatDate(detail.updated_at)} 저장`].filter(Boolean).join(' · ')}
                                        </p>
                                    )}
                                </div>
                                {detail && !isNew && (
                                    <div className="flex flex-wrap items-center gap-2">
                                        <button type="button" onClick={() => { setEditOpen((v) => !v); clear(); }} aria-expanded={editOpen} className={btnGhost}>
                                            {editOpen ? '정보 닫기' : '정보 수정'}
                                        </button>
                                        <button type="button" onClick={() => { if (confirmLeave()) { clear(); setCopying(true); } }} disabled={busy} title="사양 값과 부품 연결까지 그대로 옮긴 새 모델을 만듭니다" className={btnGhost}>복사</button>
                                        <button type="button" onClick={() => startNew(detail)} disabled={busy} className={btnGhost}>+ 하위 모델</button>
                                    </div>
                                )}
                            </div>

                            {notice && <Notice kind="ok">{notice}</Notice>}
                            {error && <Notice kind="error">{error}</Notice>}

                            {formOpen && (
                                <section aria-label="제품 정보" className="rounded-2xl border border-divide bg-white px-5 py-4">
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
                                        <Field label="모델명" htmlFor="product-model" hint={isNew ? '입찰 답변과 검색에 쓰는 기준 이름입니다.' : undefined}>
                                            <input id="product-model" autoFocus={isNew} value={draft.model} onChange={(e) => setField({ model: e.target.value })} maxLength={50} className={inputCls} />
                                        </Field>
                                        <Field label="제품 이름" htmlFor="product-name">
                                            <input id="product-name" value={draft.name} onChange={(e) => setField({ name: e.target.value })} maxLength={100} className={inputCls} />
                                        </Field>
                                        <Field label="제품 종류" htmlFor="product-category">
                                            <select id="product-category" value={draft.category} onChange={(e) => setField({ category: e.target.value })} className={selectCls}>
                                                {Object.entries(meta?.product_categories ?? { notebook: '노트북' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                            </select>
                                        </Field>
                                        <Field label="상태" htmlFor="product-status">
                                            <select id="product-status" value={draft.status} onChange={(e) => setField({ status: e.target.value })} className={selectCls}>
                                                {Object.entries(meta?.product_statuses ?? { active: '판매 중' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                            </select>
                                        </Field>
                                        <Field label="상위 모델" htmlFor="product-parent">
                                            <select id="product-parent" value={draft.parent_id ?? ''} onChange={(e) => setField({ parent_id: e.target.value || null })} className={selectCls}>
                                                <option value="">없음 (최상위 모델)</option>
                                                {parentOptions.map(({ product: p, depth }) => (
                                                    <option key={p.id} value={p.id}>{'  '.repeat(depth)}{p.model}{p.name ? ` · ${p.name}` : ''}</option>
                                                ))}
                                            </select>
                                        </Field>
                                        <Field label="비고" htmlFor="product-note">
                                            <input id="product-note" value={draft.note} onChange={(e) => setField({ note: e.target.value })} maxLength={500} className={inputCls} />
                                        </Field>
                                    </div>
                                    <div className="mt-4 flex flex-wrap items-center gap-2">
                                        {!isNew && detail && (detail.children.length > 0 ? (
                                            <span className="text-[11.5px] text-muted">하위 모델이 있어 삭제할 수 없습니다.</span>
                                        ) : (
                                            <button type="button" onClick={() => void remove()} disabled={busy} className={`${btnTiny} text-danger hover:bg-danger-soft`}>
                                                <TrashIcon /><span className="ml-1">제품 삭제</span>
                                            </button>
                                        ))}
                                        <div className="ml-auto flex items-center gap-2">
                                            {isNew ? (
                                                <>
                                                    <button type="button" onClick={() => switchTo(draft.parent_id ?? products?.[0]?.id ?? null)} className={btnGhost}>취소</button>
                                                    <button type="button" onClick={() => void save()} disabled={busy} className={btnPrimary}>{busy ? '등록 중…' : '등록'}</button>
                                                </>
                                            ) : dirty ? (
                                                <>
                                                    <button type="button" onClick={() => { setDraft(base); clear(); }} disabled={busy} className={btnGhost}>되돌리기</button>
                                                    <button type="button" onClick={() => void save()} disabled={busy} className={btnPrimary}>{busy ? '저장 중…' : '저장'}</button>
                                                </>
                                            ) : (
                                                <button type="button" onClick={() => setEditOpen(false)} className={btnGhost}>닫기</button>
                                            )}
                                        </div>
                                    </div>
                                </section>
                            )}

                            {!isNew && detail && (
                                <section aria-label="제품 사양" className="rounded-2xl border border-divide bg-white pb-2">
                                    <SpecValuesEditor
                                        key={detail.id}
                                        ownerType="product"
                                        ownerId={detail.id}
                                        title="사양"
                                        specs={detail.specs}
                                        attributes={attributes}
                                        meta={meta}
                                        scope="product"
                                        onChanged={refreshDetail}
                                        onAddDefaultAttributes={onAddDefaultAttributes}
                                        onAttributesChanged={onAttributesChanged}
                                    />
                                </section>
                            )}

                            {/* 부품 DB는 승인 부품 카탈로그라 보통 연결이 없다. 예전에 연결한 것이 있을 때만 보여준다 */}
                            {!isNew && detail && detail.components.length > 0 && (
                                <section aria-label="구성 부품" className="rounded-2xl border border-divide bg-white px-5 py-3">
                                    <h3 className="text-[13px] font-bold">구성 부품 <span className="font-semibold text-muted">{detail.components.length}</span></h3>
                                    <ul className="mt-1 flex flex-col">
                                        {detail.components.map((c) => (
                                            <li key={c.id} className="group/row flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-divide py-2 text-[12.5px] first:border-t-0">
                                                <span className="w-[72px] text-muted">{labelOf(meta?.component_kinds, c.kind)}</span>
                                                <span className="font-semibold">{c.model}{c.vendor && <span className="ml-1.5 font-normal text-muted">{c.vendor}</span>}</span>
                                                {c.link_note && <span className="text-muted">{c.link_note}</span>}
                                                <select
                                                    value={c.is_option ? 'option' : 'base'}
                                                    onChange={(e) => void setLinkOption(c.id, e.target.value === 'option', c.link_note)}
                                                    disabled={busy}
                                                    aria-label={`${c.model} 구성`}
                                                    className="ml-auto h-7 rounded-md border border-line bg-white px-1.5 text-[11.5px]"
                                                >
                                                    <option value="base">기본 구성</option>
                                                    <option value="option">옵션 구성</option>
                                                </select>
                                                <button type="button" onClick={() => void removeLink(c.id, c.model)} disabled={busy} aria-label={`${c.model} 제품에서 빼기`} title="제품에서 빼기" className={`${btnTiny} hover:text-danger`}><TrashIcon /></button>
                                            </li>
                                        ))}
                                    </ul>
                                </section>
                            )}
                        </>
                    )}
                </div>
            </main>
            {copying && detail && (
                <CopyProductDialog source={detail} products={products ?? []} onDone={(done) => void afterCopy(done)} onCancel={() => setCopying(false)} />
            )}
        </div>
    );
}
