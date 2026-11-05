import { useEffect, useState } from 'react';
import { TrashIcon } from '../components/icons';
import { specApi, type Component, type ComponentDetail, type ComponentInput, type SpecAttribute, type SpecMeta } from './api';
import { SpecValuesEditor } from './SpecValuesEditor';
import { btnDanger, btnGhost, btnPrimary, errorMessage, formatDate, inputCls, labelOf, selectCls } from './styles';
import { Card, Field, ListItem, Notice, Pill } from './ui';

const EMPTY: ComponentInput = { kind: 'cpu', model: '', vendor: '', note: '' };
type ActiveId = string | 'new' | null;

function toInput(c: ComponentDetail): ComponentInput {
    return { kind: c.kind, model: c.model, vendor: c.vendor, note: c.note };
}

/** 부품 탭: CPU·GPU·SSD 등 부품과 그 사양 값. 사내 문서에 없는 코어 수·클럭 같은 값을 여기에 둔다 */
export function ComponentsTab({
    meta,
    attributes,
    components,
    onChanged,
    onAddDefaultAttributes,
}: {
    meta: SpecMeta | null;
    attributes: SpecAttribute[];
    /** 상위(SpecSection)가 들고 있는 부품 목록. 제품 탭의 연결 선택에도 쓰여서 위에서 관리한다 */
    components: Component[] | null;
    onChanged: () => Promise<void>;
    onAddDefaultAttributes: () => Promise<void>;
}) {
    const [activeId, setActiveId] = useState<ActiveId>(null);
    const [detail, setDetail] = useState<ComponentDetail | null>(null);
    const [detailKey, setDetailKey] = useState(0);
    const [draft, setDraft] = useState<ComponentInput>(EMPTY);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');
    const [kindFilter, setKindFilter] = useState('');

    // 아직 고른 게 없으면 목록의 첫 부품을 연 것으로 본다 (효과로 상태를 맞추지 않는다)
    const resolvedId: ActiveId = activeId === null ? (components?.[0]?.id ?? null) : activeId;

    useEffect(() => {
        if (!resolvedId || resolvedId === 'new') return;
        let cancelled = false;
        specApi.getComponent(resolvedId)
            .then((d) => {
                if (cancelled) return;
                setDetail(d);
                setDraft(toInput(d));
            })
            .catch((e) => { if (!cancelled) setError(errorMessage(e, '부품 정보를 불러오지 못했습니다.')); });
        return () => { cancelled = true; };
    }, [resolvedId, detailKey]);

    const isNew = resolvedId === 'new';
    const base = detail && !isNew ? toInput(detail) : EMPTY;
    const dirty = (Object.keys(EMPTY) as (keyof ComponentInput)[]).some((k) => draft[k] !== base[k]);
    const canSave = !busy && draft.model.trim().length > 0 && (isNew || dirty);

    function clear() { setNotice(''); setError(''); }

    function switchTo(id: ActiveId) {
        if (id === resolvedId) return;
        if (dirty && !window.confirm('저장하지 않은 변경 사항이 있습니다. 버리고 이동할까요?')) return;
        clear();
        setActiveId(id);
        if (id === 'new') { setDetail(null); setDraft({ ...EMPTY, kind: kindFilter || EMPTY.kind }); }
    }

    const refreshDetail = () => { setDetailKey((k) => k + 1); void onChanged(); };

    async function save() {
        if (!canSave) return;
        setBusy(true);
        clear();
        try {
            const saved = isNew || !detail ? await specApi.createComponent(draft) : await specApi.updateComponent(detail.id, draft);
            await onChanged();
            setDetail(saved);
            setDraft(toInput(saved));
            setActiveId(saved.id);
            setNotice(isNew ? `'${saved.model}' 부품을 등록했습니다. 아래에서 사양 값을 넣으세요.` : '저장했습니다.');
        } catch (e) {
            setError(errorMessage(e, '저장하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    async function remove() {
        if (!detail || isNew || busy) return;
        if (!window.confirm(`'${detail.model}' 부품을 삭제할까요?\n사양 값 ${detail.spec_count}건도 함께 지워집니다.`)) return;
        setBusy(true);
        clear();
        try {
            await specApi.deleteComponent(detail.id);
            await onChanged();
            setDetail(null);
            setActiveId(null);
            setNotice(`'${detail.model}' 부품을 삭제했습니다.`);
        } catch (e) {
            setError(errorMessage(e, '삭제하지 못했습니다.'));
        } finally {
            setBusy(false);
        }
    }

    const kinds = Object.entries(meta?.component_kinds ?? {});
    const visible = (components ?? []).filter((c) => !kindFilter || c.kind === kindFilter);

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[260px] lg:w-[290px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                <h1 className="text-[16px] font-bold">부품</h1>
                <p className="mt-1 text-[12px] leading-5 text-muted">CPU 코어 수, SSD 인터페이스처럼 제품 문서에 없는 값을 부품 단위로 둡니다. 제품 탭에서 연결합니다.</p>
                <button
                    type="button"
                    onClick={() => switchTo('new')}
                    disabled={components === null}
                    aria-pressed={isNew}
                    className={`mt-4 w-full h-9 rounded-lg border text-[12px] font-semibold transition-colors disabled:opacity-40 ${isNew ? 'border-brand/25 bg-brand-tint text-brand-hover' : 'border-line hover:bg-chip'}`}
                >
                    + 새 부품
                </button>
                {kinds.length > 0 && (
                    <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} aria-label="부품 종류 필터" className={`${selectCls} mt-3 !h-8 text-[12px]`}>
                        <option value="">모든 종류</option>
                        {kinds.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                )}
                <nav aria-label="부품 목록" className="mt-3 flex md:flex-col gap-1.5 overflow-x-auto md:overflow-visible">
                    {components === null && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                    {components?.length === 0 && <p className="text-[12px] text-muted px-1 py-2">아직 등록된 부품이 없습니다.</p>}
                    {components && components.length > 0 && visible.length === 0 && <p className="text-[12px] text-muted px-1 py-2">이 종류의 부품이 없습니다.</p>}
                    {visible.map((c) => (
                        <div key={c.id} className="shrink-0 min-w-[200px] md:min-w-0">
                            <ListItem
                                active={resolvedId === c.id}
                                title={c.model}
                                subtitle={[labelOf(meta?.component_kinds, c.kind), c.vendor, `사양 ${c.spec_count}`, c.product_count ? `제품 ${c.product_count}` : ''].filter(Boolean).join(' · ')}
                                onClick={() => switchTo(c.id)}
                            />
                        </div>
                    ))}
                </nav>
            </aside>

            <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8">
                <div className="mx-auto max-w-[960px] flex flex-col gap-5">
                    {resolvedId === null ? (
                        <p className="text-[13px] text-muted">왼쪽에서 부품을 고르거나 새 부품을 등록하세요.</p>
                    ) : (
                        <>
                            <div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <h2 className="text-[22px] font-bold tracking-tight break-all">{isNew ? '새 부품' : detail?.model ?? '…'}</h2>
                                    {detail && !isNew && <Pill>{labelOf(meta?.component_kinds, detail.kind)}</Pill>}
                                </div>
                                <p className="mt-1.5 text-[12.5px] text-muted">
                                    {isNew ? '종류와 모델명을 입력해 저장하면 사양 값을 넣을 수 있습니다.' : detail ? `${formatDate(detail.updated_at)} 저장` : ''}
                                </p>
                            </div>

                            {notice && <Notice kind="ok">{notice}</Notice>}
                            {error && <Notice kind="error">{error}</Notice>}

                            <Card
                                title="부품 정보"
                                aside={
                                    <div className="flex items-center gap-2">
                                        {!isNew && detail && (
                                            <button type="button" onClick={() => void remove()} disabled={busy || detail.product_count > 0} title={detail.product_count > 0 ? '제품에 연결된 부품은 지울 수 없습니다. 제품에서 먼저 빼세요.' : undefined} className={btnDanger}><TrashIcon />삭제</button>
                                        )}
                                        <button type="button" onClick={() => void save()} disabled={!canSave} className={btnPrimary}>
                                            {busy ? '저장 중…' : isNew ? '등록' : '저장'}
                                        </button>
                                    </div>
                                }
                            >
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <Field label="종류" htmlFor="component-kind">
                                        <select id="component-kind" value={draft.kind} onChange={(e) => { setDraft((d) => ({ ...d, kind: e.target.value })); clear(); }} className={selectCls}>
                                            {(kinds.length ? kinds : [['other', '기타']]).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="모델명" htmlFor="component-model" hint="제조사 표기 그대로. 예: AMD Ryzen AI 7 350, Core i7-1355U">
                                        <input id="component-model" value={draft.model} onChange={(e) => { setDraft((d) => ({ ...d, model: e.target.value })); clear(); }} maxLength={100} placeholder="AMD Ryzen AI 7 350" className={inputCls} />
                                    </Field>
                                    <Field label="제조사" htmlFor="component-vendor">
                                        <input id="component-vendor" value={draft.vendor} onChange={(e) => { setDraft((d) => ({ ...d, vendor: e.target.value })); clear(); }} maxLength={50} placeholder="AMD" className={inputCls} />
                                    </Field>
                                    <Field label="비고" htmlFor="component-note">
                                        <input id="component-note" value={draft.note} onChange={(e) => { setDraft((d) => ({ ...d, note: e.target.value })); clear(); }} maxLength={500} placeholder="예: 벤더 스펙 시트 2025-04 기준" className={inputCls} />
                                    </Field>
                                </div>
                            </Card>

                            {!isNew && detail && (
                                <>
                                    <Card title={`사양 값 ${detail.specs.length}`}>
                                        <SpecValuesEditor
                                            ownerType="component"
                                            ownerId={detail.id}
                                            specs={detail.specs}
                                            attributes={attributes}
                                            meta={meta}
                                            scope={detail.kind}
                                            onChanged={refreshDetail}
                                            onAddDefaultAttributes={onAddDefaultAttributes}
                                        />
                                    </Card>
                                    <Card title={`사용 제품 ${detail.products.length}`}>
                                        {detail.products.length === 0 ? (
                                            <p className="text-[12.5px] text-muted py-1">이 부품을 쓰는 제품이 없습니다. 제품 탭의 부품 구성에서 연결합니다.</p>
                                        ) : (
                                            <ul className="flex flex-wrap gap-2">
                                                {detail.products.map((p) => (
                                                    <li key={p.id} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-[12.5px]">
                                                        <span className="font-semibold">{p.model}</span>
                                                        {p.name && <span className="text-muted">{p.name}</span>}
                                                        <Pill tone={p.is_option ? 'warn' : 'brand'}>{p.is_option ? '옵션' : '기본'}</Pill>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </Card>
                                </>
                            )}

                            {isNew && (
                                <p className="text-[12px] text-muted">
                                    <button type="button" onClick={() => switchTo(components?.[0]?.id ?? null)} className={btnGhost}>취소</button>
                                </p>
                            )}
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}
