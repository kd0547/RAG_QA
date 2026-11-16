import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { linkProps } from '../lib/router';
import { reviewPath } from '../rag/api';
import { graphApi } from './api';
import { EntityPicker, TypeDot, type PickedEntity } from './EntityPicker';
import { errorText } from './errors';
import { entityMeta, useGraphSchema } from './schemaContext';
import { SpecDiffBox, TypeChanger } from './EntityEditExtras';
import { EntityProperties } from './GraphEditing';
import { ModelHierarchy, SpecAttributeSection, SpecValuesSection } from './SpecPanels';
import { groupRelations } from './relationGroups';
import { AddRelation, RelationDetail, RelationGroups } from './RelationViews';
import type { GraphEntityDetail, GraphNode, GraphRelation } from './types';

/** "그래프에서 고르기": 부모가 다음 노드 클릭을 이 콜백으로 넘긴다 */
export type RequestPick = (onPicked: (node: GraphNode) => void) => void;

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
    return (
        <section className="border-t border-divide px-4 py-3.5">
            <h3 className="text-[12px] font-bold text-ink/80">
                {title}
                {count !== undefined && <span className="ml-1 font-semibold text-muted">{count}</span>}
            </h3>
            <div className="mt-2">{children}</div>
        </section>
    );
}

/** 개체 상세와 편집 (이름 바꾸기, 관계 편집·추가, 다른 개체에 합치기) */
export function EntityPanel({
    entityId,
    version,
    onOpenEntity,
    onFocus,
    onChanged,
    onMerged,
    requestPick,
}: {
    entityId: number;
    /** 바뀌면 다시 불러온다 */
    version: number;
    onOpenEntity: (id: number) => void;
    onFocus: (id: number) => void;
    /** 그래프가 바뀌었다 (다시 그리기) */
    onChanged: () => void;
    /** sourceId 개체가 targetId에 합쳐져 사라졌다 */
    onMerged: (sourceId: number, targetId: number) => void;
    requestPick: RequestPick;
}) {
    const { schema } = useGraphSchema();
    const [entity, setEntity] = useState<GraphEntityDetail | null>(null);
    const [loadError, setLoadError] = useState('');
    const [renaming, setRenaming] = useState<string | null>(null);
    const [mergeTarget, setMergeTarget] = useState<PickedEntity | null>(null);
    const [busy, setBusy] = useState(false);
    const [actionError, setActionError] = useState('');
    const [reload, setReload] = useState(0);

    useEffect(() => {
        let ignore = false;
        graphApi.entity(entityId).then((detail) => {
            if (!ignore) {
                setEntity(detail);
                setLoadError('');
            }
        }).catch((e: unknown) => {
            if (!ignore) setLoadError(errorText(e));
        });
        return () => { ignore = true; };
    }, [entityId, version, reload]);

    const changed = () => {
        setReload((n) => n + 1);
        onChanged();
    };

    if (loadError) return <p role="alert" className="p-4 text-[12.5px] text-danger">{loadError}</p>;
    if (!entity || entity.id !== entityId) return <p className="p-4 text-[12.5px] text-muted">불러오는 중…</p>;

    const meta = entityMeta(schema, entity.type);
    const otherAliases = entity.aliases.filter((a) => a !== entity.name);

    const rename = async () => {
        if (renaming === null || !renaming.trim() || renaming.trim() === entity.name) {
            setRenaming(null);
            return;
        }
        setBusy(true);
        setActionError('');
        try {
            setEntity(await graphApi.renameEntity(entity.id, renaming.trim(), entity.revision));
            setRenaming(null);
            onChanged();
        } catch (e) {
            setActionError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    const merge = async () => {
        if (mergeTarget?.kind !== 'existing') return;
        setBusy(true);
        setActionError('');
        try {
            const merged = await graphApi.mergeEntity(entity.id, mergeTarget.id, entity.revision, mergeTarget.revision);
            setMergeTarget(null);
            onMerged(entity.id, merged.id);
        } catch (e) {
            setActionError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div>
            <div className="px-4 pb-3.5 pt-4">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-chip px-2 py-0.5 text-[11px] font-bold" style={{ color: meta.color === '#141C2B' ? undefined : meta.color }}>
                    <TypeDot type={entity.type} />
                    {meta.label}
                </span>
                {renaming !== null ? (
                    <form className="mt-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); void rename(); }}>
                        <input
                            autoFocus
                            aria-label="개체 이름"
                            value={renaming}
                            onChange={(e) => setRenaming(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Escape') setRenaming(null); }}
                            className="h-9 min-w-0 flex-1 rounded-lg border border-line px-2.5 text-[14px] font-bold focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10"
                        />
                        <button type="submit" disabled={busy} className="h-9 rounded-lg bg-brand px-3 text-[12px] font-bold text-white disabled:opacity-50">저장</button>
                    </form>
                ) : (
                    <div className="mt-1.5 flex items-start gap-2">
                        <h2 className="min-w-0 flex-1 break-words text-[17px] font-bold leading-6">{entity.name}</h2>
                        {schema.editing_enabled && <button type="button" onClick={() => setRenaming(entity.name)} className="mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold text-muted hover:bg-chip hover:text-ink">{entity.ref_id ? '표시명 수정' : '이름 수정'}</button>}
                    </div>
                )}
                {otherAliases.length > 0 && (
                    <p className="mt-1.5 text-[11.5px] leading-5 text-muted">
                        다른 표기: {otherAliases.join(', ')}
                    </p>
                )}
                {actionError && <p role="alert" className="mt-2 text-[11.5px] text-danger">{actionError}</p>}
                <TypeChanger entity={entity} changed={changed} />
                <button
                    type="button"
                    onClick={() => onFocus(entity.id)}
                    className="mt-3 h-8 w-full rounded-lg border border-line text-[12px] font-semibold hover:bg-chip"
                >
                    이 개체 중심으로 보기
                </button>
            </div>

            <SpecDiffBox entity={entity} changed={changed} />
            <ModelHierarchy entity={entity} onOpenEntity={onOpenEntity} />
            <SpecValuesSection entity={entity} />
            <SpecAttributeSection entity={entity} onOpenEntity={onOpenEntity} />
            <EntityProperties key={entity.id} entity={entity} changed={changed} removed={() => onMerged(entity.id, 0)} />
            <Section title="관계" count={groupRelations(entity.relations).length}>
                <RelationGroups key={entity.id} entityId={entity.id} relations={entity.relations} onOpenEntity={onOpenEntity} onChanged={changed} />
                {schema.editing_enabled && (
                    <div className="mt-2.5">
                        <AddRelation key={entity.id} entity={entity} onCreated={changed}
                            onPickFromGraph={(done) => requestPick((node) => {
                                if (node.id !== entity.id) done({ kind: 'existing', id: node.id, type: node.type, name: node.name, revision: node.revision });
                            })} />
                    </div>
                )}
            </Section>

            <Section title="나온 문서" count={entity.mentions.length}>
                {entity.mentions.length === 0 ? (
                    <p className="text-[12px] text-muted">문서에 나온 위치가 없습니다 (사람이 넣었거나 기본 개념).</p>
                ) : (
                    <ul className="space-y-1">
                        {entity.mentions.map((m) => (
                            <li key={`${m.file_id}-${m.page}`}>
                                <a {...linkProps(reviewPath(m.file_id))} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-chip" title="파일 검수 화면에서 열기">
                                    <span className="min-w-0 flex-1 truncate">{m.original_name}</span>
                                    <span className="shrink-0 text-muted">{m.page}쪽</span>
                                </a>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            {schema.editing_enabled && <Section title="다른 개체와 합치기">
                <p className="mb-2 text-[11.5px] leading-5 text-muted">
                    같은 대상이 다른 이름으로 나뉘어 있을 때 씁니다. 이 개체의 관계와 문서가 고른 개체로 옮겨지고, 이 이름은 그 개체의 다른 표기가 됩니다.
                </p>
                {mergeTarget?.kind === 'existing' ? (
                    <div className="rounded-lg border border-warn/30 bg-warn-soft/40 p-2.5 text-[12px] leading-5">
                        <b>{entity.name}</b>을(를) <b>{mergeTarget.name}</b>에 합칩니다. <b>{entity.name}</b> 개체는 사라집니다.
                        <div className="mt-2 flex justify-end gap-1.5">
                            <button type="button" onClick={() => setMergeTarget(null)} className="h-7 rounded-md px-2 text-[11.5px] font-semibold text-muted hover:bg-white">취소</button>
                            <button type="button" disabled={busy} onClick={() => void merge()} className="h-7 rounded-md bg-ink px-2.5 text-[11.5px] font-bold text-white disabled:opacity-50">합치기</button>
                        </div>
                    </div>
                ) : (
                    <EntityPicker label="합칠 대상 개체" placeholder="합칠 개체 찾기" excludeId={entity.id} onPick={setMergeTarget} />
                )}
            </Section>}
        </div>
    );
}

/** 선을 눌렀을 때: 관계 하나를 문장으로 보이고 바꾸기·지우기 */
export function EdgePanel({
    relation,
    siblings = [],
    onOpenEntity,
    onReplaced,
    onDeleted,
}: {
    relation: GraphRelation;
    /** 같은 관계의 다른 출처 행 */
    siblings?: GraphRelation[];
    onOpenEntity: (id: number) => void;
    onReplaced: (relation: GraphRelation) => void;
    onDeleted: () => void;
}) {
    return (
        <div className="p-4">
            <p className="text-[11px] font-bold text-muted">관계</p>
            <div className="mt-2">
                <RelationDetail key={relation.id} rows={[relation, ...siblings]} onOpenEntity={onOpenEntity}
                    onChanged={(result) => (result ? onReplaced(result) : onDeleted())} />
            </div>
            <p className="mt-3 text-[11.5px] leading-5 text-muted">
                문서에서 뽑은 관계를 고치거나 지우면, 그 문서를 다시 추출해도 원래 관계로 돌아가지 않습니다.
            </p>
        </div>
    );
}
