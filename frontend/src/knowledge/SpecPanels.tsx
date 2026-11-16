import { useEffect, useState } from 'react';

import { request } from '../lib/http';
import { linkProps } from '../lib/router';
import { TypeDot } from './EntityPicker';
import type { GraphEntityDetail, SpecValueItem } from './types';

/**
 * 개체 패널의 사양 DB 영역 (지시서 GR4-2·GR4-7).
 * - 모델 계층: 상위 경로와 하위 모델 (variant_of)
 * - 사양 DB: 제품·부품 노드의 그때 사양 값 (분류별로 접기)
 * - 사양 값 노드: 속성 이름·단위·숫자 값과 이 값을 가진 대상
 * 그래프 편집은 사양 DB를 고치지 않는다. 값은 사양 화면에서 바꾼다.
 */

let categoryCache: Promise<Record<string, string>> | null = null;
function categoryLabels(): Promise<Record<string, string>> {
    categoryCache ??= request<{ attribute_categories: Record<string, string> }>('/specs/meta')
        .then((m) => m.attribute_categories).catch(() => ({}));
    return categoryCache;
}

function specPagePath(entity: Pick<GraphEntityDetail, 'ref_type' | 'ref_id'>): string {
    if (!entity.ref_id || (entity.ref_type !== 'product' && entity.ref_type !== 'component')) return '/spec';
    return `/spec?tab=${entity.ref_type === 'component' ? 'components' : 'products'}&${entity.ref_type}=${encodeURIComponent(entity.ref_id)}`;
}

export function ModelHierarchy({ entity, onOpenEntity }: { entity: GraphEntityDetail; onOpenEntity: (id: number) => void }) {
    const { ancestors, children } = entity.hierarchy ?? { ancestors: [], children: [] };
    if (!ancestors.length && !children.length) return null;
    return (
        <section aria-label="모델 계층" className="border-t border-divide px-4 py-3.5 text-[12px]">
            <h3 className="text-[12px] font-bold text-ink/80">모델 계층</h3>
            <p className="mt-2 flex flex-wrap items-center gap-1 text-muted">
                {ancestors.map((a) => (
                    <span key={a.id} className="flex items-center gap-1">
                        <button type="button" onClick={() => onOpenEntity(a.id)} className="inline-flex items-center gap-1 rounded px-1 font-semibold text-ink hover:bg-chip">
                            <TypeDot type={a.type} />{a.name}
                        </button>›
                    </span>
                ))}
                <span className="inline-flex items-center gap-1 rounded bg-chip px-1 font-bold text-ink"><TypeDot type={entity.type} />{entity.name}</span>
            </p>
            {children.length > 0 && <>
                <p className="mt-2 text-[11.5px] text-muted">하위 모델 {children.length}</p>
                <ul className="mt-1 space-y-0.5">
                    {children.map((c) => (
                        <li key={c.id}>
                            <button type="button" onClick={() => onOpenEntity(c.id)} className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left hover:bg-chip">
                                <TypeDot type={c.type} /><span className="truncate">{c.name}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            </>}
            <p className="mt-2 text-[11px] text-muted">제품군의 값은 하위 모델의 값이 아닙니다. 모델별로 확인하세요.</p>
        </section>
    );
}

function valueLabel(v: SpecValueItem): string {
    const tags = [v.is_option ? '옵션' : '', v.inherited_from ? `상위 모델 ${v.inherited_from}` : '', v.via_component ? `부품 ${v.via_component}` : '']
        .filter(Boolean);
    return `${v.value_text}${v.unit && !v.value_text.endsWith(v.unit) ? ` ${v.unit}` : ''}${tags.length ? ` [${tags.join(', ')}]` : ''}`;
}

export function SpecValuesSection({ entity }: { entity: GraphEntityDetail }) {
    const [labels, setLabels] = useState<Record<string, string>>({});
    useEffect(() => { void categoryLabels().then(setLabels); }, []);
    if (!entity.ref_id || (entity.ref_type !== 'product' && entity.ref_type !== 'component')) return null;
    const values = entity.spec?.values ?? [];
    const groups = new Map<string, SpecValueItem[]>();
    for (const v of values) groups.set(v.category, [...(groups.get(v.category) ?? []), v]);
    return (
        <section aria-label="사양 DB" className="border-t border-divide px-4 py-3.5 text-[12px]">
            <div className="flex items-center justify-between">
                <h3 className="text-[12px] font-bold text-ink/80">사양 DB <span className="font-semibold text-muted">{values.length}</span></h3>
                <a {...linkProps(specPagePath(entity))} className="text-[11.5px] font-semibold text-brand underline">사양 화면에서 열기</a>
            </div>
            {entity.spec === null && <p className="mt-2 text-muted">사양 값을 읽지 못했습니다.</p>}
            {entity.spec && values.length === 0 && <p className="mt-2 text-muted">등록된 사양 값이 없습니다.</p>}
            <div className="mt-2 space-y-1">
                {[...groups.entries()].map(([category, items]) => (
                    <details key={category} className="rounded border border-line">
                        <summary className="cursor-pointer px-2 py-1 font-semibold">{labels[category] ?? category} <span className="text-muted">{items.length}</span></summary>
                        <dl className="space-y-0.5 px-2 pb-2">
                            {items.map((v) => (
                                <div key={`${v.spec_value_id}-${v.via_component ?? ''}`} className="flex gap-2">
                                    <dt className="w-28 shrink-0 text-muted">{v.attribute_name}</dt>
                                    <dd className="min-w-0 break-words">{valueLabel(v)}</dd>
                                </div>
                            ))}
                        </dl>
                    </details>
                ))}
            </div>
            <p className="mt-2 text-[11px] text-muted">지금 사양 DB 값입니다. 그래프에서 고쳐도 사양 DB는 바뀌지 않습니다.</p>
        </section>
    );
}

export function SpecAttributeSection({ entity, onOpenEntity }: { entity: GraphEntityDetail; onOpenEntity: (id: number) => void }) {
    const attribute = entity.spec_attribute;
    if (!attribute) return null;
    const holders = entity.relations.filter((r) => r.type === 'has_spec' && r.target_id === entity.id);
    return (
        <section aria-label="사양 값" className="border-t border-divide px-4 py-3.5 text-[12px]">
            <h3 className="text-[12px] font-bold text-ink/80">사양 값</h3>
            <dl className="mt-2 space-y-0.5">
                <div className="flex gap-2"><dt className="w-20 text-muted">속성</dt><dd>{attribute.name} <span className="text-muted">({attribute.key})</span></dd></div>
                {attribute.unit && <div className="flex gap-2"><dt className="w-20 text-muted">단위</dt><dd>{attribute.unit}</dd></div>}
                {attribute.value_num !== null && attribute.data_type === 'number' && <div className="flex gap-2"><dt className="w-20 text-muted">숫자 값</dt><dd>{attribute.value_num}</dd></div>}
            </dl>
            <p className="mt-2 text-[11.5px] text-muted">이 값을 가진 대상 {holders.length}</p>
            <ul className="mt-1 space-y-0.5">
                {holders.map((r) => (
                    <li key={r.id}>
                        <button type="button" onClick={() => onOpenEntity(r.source_id)} className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left hover:bg-chip">
                            <TypeDot type={r.source_type} /><span className="truncate">{r.source_name}</span>
                        </button>
                    </li>
                ))}
            </ul>
        </section>
    );
}
