import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { linkProps } from '../lib/router';
import { reviewPath } from '../rag/api';
import { graphApi } from './api';
import { EntityPicker, TypeDot, type PickedEntity } from './EntityPicker';
import { errorText } from './errors';
import { ENTITY_META, ORIGIN_META, RELATION_META, RELATION_TYPES } from './meta';
import type { GraphEntityDetail, GraphNode, GraphRelation, RelationType } from './types';

/** "그래프에서 고르기": 부모가 다음 노드 클릭을 이 콜백으로 넘긴다 */
export type RequestPick = (onPicked: (node: GraphNode) => void) => void;

function OriginBadge({ relation }: { relation: Pick<GraphRelation, 'origin'> }) {
    const meta = ORIGIN_META[relation.origin];
    return <span className={`shrink-0 rounded-full border px-1.5 py-px text-[10px] font-semibold ${meta.className}`}>{meta.label}</span>;
}

function evidenceText(relation: Pick<GraphRelation, 'original_name' | 'page'>): string | null {
    if (!relation.original_name) return null;
    return relation.page !== null ? `${relation.original_name} · ${relation.page}쪽` : relation.original_name;
}

/**
 * 관계 한 줄: 종류 바꾸기, 방향 뒤집기, 지우기.
 * 문서에서 뽑은 관계를 고치거나 지우면 서버가 기억해서, 문서를 다시 뽑아도 원래대로 돌아가지 않는다.
 */
export function RelationRow({
    relation,
    perspectiveId,
    onOpenEntity,
    onReplaced,
    onDeleted,
}: {
    relation: GraphRelation;
    /** 이 개체 입장에서 보여준다 (상대 개체를 크게). 없으면 출발 → 도착 */
    perspectiveId?: number;
    onOpenEntity: (id: number) => void;
    onReplaced: (relation: GraphRelation) => void;
    onDeleted: () => void;
}) {
    const [busy, setBusy] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const [error, setError] = useState('');

    const outgoing = perspectiveId === undefined || relation.source_id === perspectiveId;
    const other = outgoing
        ? { id: relation.target_id, type: relation.target_type, name: relation.target_name }
        : { id: relation.source_id, type: relation.source_type, name: relation.source_name };
    const evidence = evidenceText(relation);

    const run = async (action: () => Promise<void>) => {
        setBusy(true);
        setError('');
        try {
            await action();
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy(false);
        }
    };

    return (
        <li className="rounded-lg border border-divide bg-white px-3 py-2">
            <div className="flex items-center gap-2">
                {perspectiveId !== undefined && (
                    <span className="shrink-0 text-[12px] font-bold text-muted" title={outgoing ? '이 개체에서 나가는 관계' : '이 개체로 들어오는 관계'}>
                        {outgoing ? '→' : '←'}
                    </span>
                )}
                {perspectiveId === undefined ? (
                    <span className="min-w-0 flex-1 text-[12.5px] font-semibold">
                        <button type="button" onClick={() => onOpenEntity(relation.source_id)} className="hover:underline">{relation.source_name}</button>
                        <span className="mx-1 text-muted">→</span>
                        <button type="button" onClick={() => onOpenEntity(relation.target_id)} className="hover:underline">{relation.target_name}</button>
                    </span>
                ) : (
                    <button type="button" onClick={() => onOpenEntity(other.id)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[12.5px] font-semibold hover:underline">
                        <TypeDot type={other.type} />
                        <span className="truncate">{other.name}</span>
                    </button>
                )}
                <OriginBadge relation={relation} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <select
                    aria-label="관계 종류"
                    value={relation.type}
                    disabled={busy}
                    onChange={(e) => {
                        const type = e.target.value as RelationType;
                        void run(async () => onReplaced(await graphApi.updateRelation(relation.id, { type })));
                    }}
                    className="h-7 rounded-md border border-line bg-white px-1.5 text-[11.5px] font-semibold disabled:opacity-50"
                >
                    {RELATION_TYPES.map((t) => <option key={t} value={t}>{RELATION_META[t].label} ({RELATION_META[t].hint})</option>)}
                </select>
                <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(async () => onReplaced(await graphApi.updateRelation(relation.id, { reverse: true })))}
                    title="출발과 도착을 바꿉니다"
                    className="h-7 rounded-md border border-line px-2 text-[11.5px] font-semibold text-ink/70 hover:bg-chip disabled:opacity-50"
                >
                    ⇄ 방향
                </button>
                {confirming ? (
                    <span className="ml-auto flex items-center gap-1">
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => void run(async () => {
                                await graphApi.deleteRelation(relation.id);
                                onDeleted();
                            })}
                            className="h-7 rounded-md bg-danger px-2 text-[11.5px] font-bold text-white hover:opacity-90 disabled:opacity-50"
                        >
                            지우기
                        </button>
                        <button type="button" onClick={() => setConfirming(false)} className="h-7 rounded-md px-2 text-[11.5px] font-semibold text-muted hover:bg-chip">취소</button>
                    </span>
                ) : (
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => setConfirming(true)}
                        className="ml-auto h-7 rounded-md px-2 text-[11.5px] font-semibold text-danger hover:bg-danger-surface disabled:opacity-50"
                    >
                        삭제
                    </button>
                )}
            </div>
            {confirming && (
                <p className="mt-1.5 text-[11px] leading-4 text-muted">
                    두 개체 사이의 이 종류 관계를 모두 지웁니다. 문서를 다시 추출해도 되살아나지 않습니다.
                </p>
            )}
            {evidence && (
                relation.file_id ? (
                    <a {...linkProps(reviewPath(relation.file_id))} className="mt-1 block truncate text-[11px] text-muted hover:text-brand-hover hover:underline">
                        근거: {evidence}
                    </a>
                ) : <p className="mt-1 truncate text-[11px] text-muted">근거: {evidence}</p>
            )}
            {error && <p role="alert" className="mt-1 text-[11px] text-danger">{error}</p>}
        </li>
    );
}

/** 이 개체에서 새 관계 넣기 */
function AddRelationForm({
    entity,
    onCreated,
    requestPick,
}: {
    entity: GraphEntityDetail;
    onCreated: (relation: GraphRelation) => void;
    requestPick: RequestPick;
}) {
    const [type, setType] = useState<RelationType>(entity.type === 'certification' ? 'part_of' : 'has_component');
    const [outgoing, setOutgoing] = useState(true);
    const [target, setTarget] = useState<PickedEntity | null>(null);
    const [picking, setPicking] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');

    const save = async () => {
        if (!target) return;
        setSaving(true);
        setError('');
        try {
            let relation: GraphRelation;
            if (outgoing) {
                relation = await graphApi.createRelation(target.kind === 'existing'
                    ? { source_id: entity.id, type, target_id: target.id }
                    : { source_id: entity.id, type, new_target: { type: target.type, name: target.name } });
            } else {
                // 들어오는 관계: 새 개체가 출발점이면 먼저 이 개체 쪽으로 만든 뒤 뒤집는다
                if (target.kind === 'existing') {
                    relation = await graphApi.createRelation({ source_id: target.id, type, target_id: entity.id });
                } else {
                    const created = await graphApi.createRelation({ source_id: entity.id, type, new_target: { type: target.type, name: target.name } });
                    relation = await graphApi.updateRelation(created.id, { reverse: true });
                }
            }
            setTarget(null);
            onCreated(relation);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="rounded-lg border border-dashed border-line bg-surface p-3">
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-2 text-[12px]">
                <span className="font-semibold text-muted">관계</span>
                <select
                    aria-label="새 관계 종류"
                    value={type}
                    onChange={(e) => setType(e.target.value as RelationType)}
                    className="h-8 rounded-md border border-line bg-white px-1.5 text-[12px]"
                >
                    {RELATION_TYPES.map((t) => <option key={t} value={t}>{RELATION_META[t].label} ({RELATION_META[t].hint})</option>)}
                </select>
                <span className="font-semibold text-muted">방향</span>
                <div role="group" aria-label="관계 방향" className="flex rounded-md bg-chip p-0.5">
                    {[true, false].map((value) => (
                        <button
                            key={String(value)}
                            type="button"
                            aria-pressed={outgoing === value}
                            onClick={() => setOutgoing(value)}
                            className={`h-7 flex-1 rounded px-2 text-[11.5px] font-semibold ${outgoing === value ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted'}`}
                        >
                            {value ? '이 개체 → 대상' : '대상 → 이 개체'}
                        </button>
                    ))}
                </div>
                <span className="font-semibold text-muted">대상</span>
                {target ? (
                    <div className="flex min-w-0 items-center gap-1.5 rounded-md border border-line bg-white px-2 py-1">
                        <TypeDot type={target.type} />
                        <span className="min-w-0 flex-1 truncate font-semibold">{target.name}</span>
                        {target.kind === 'new' && <span className="shrink-0 text-[10.5px] text-brand-hover">새 {ENTITY_META[target.type].label}</span>}
                        <button type="button" onClick={() => setTarget(null)} aria-label="대상 지우기" className="shrink-0 px-1 text-muted hover:text-ink">×</button>
                    </div>
                ) : (
                    <div className="flex min-w-0 gap-1.5">
                        <div className="min-w-0 flex-1">
                            <EntityPicker label="관계 대상 개체" excludeId={entity.id} allowCreate onPick={setTarget}
                                defaultNewType={type === 'has_component' ? 'component' : type === 'has_certification' ? 'certification'
                                    : type === 'has_number' ? 'cert_number' : type === 'issued_by' ? 'organization'
                                        : type === 'complies_with' ? 'standard' : type === 'part_of' ? 'concept' : 'product'} />
                        </div>
                        <button
                            type="button"
                            aria-pressed={picking}
                            onClick={() => {
                                setPicking(true);
                                requestPick((node) => {
                                    setPicking(false);
                                    if (node.id !== entity.id) setTarget({ kind: 'existing', id: node.id, type: node.type, name: node.name });
                                });
                            }}
                            title="그래프에서 노드를 눌러 고릅니다"
                            className={`h-9 shrink-0 rounded-lg border px-2 text-[11.5px] font-semibold ${picking ? 'border-brand bg-brand-tint text-brand-hover' : 'border-line bg-white text-ink/70 hover:bg-chip'}`}
                        >
                            {picking ? '노드를 누르세요' : '그래프에서'}
                        </button>
                    </div>
                )}
            </div>
            {error && <p role="alert" className="mt-2 text-[11.5px] text-danger">{error}</p>}
            <div className="mt-2.5 flex justify-end">
                <button
                    type="button"
                    disabled={!target || saving}
                    onClick={() => void save()}
                    className="h-8 rounded-lg bg-brand px-3 text-[12px] font-bold text-white hover:bg-brand-hover disabled:opacity-40"
                >
                    {saving ? '저장 중…' : '관계 추가'}
                </button>
            </div>
        </div>
    );
}

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

    const meta = ENTITY_META[entity.type];
    const otherAliases = entity.aliases.filter((a) => a !== entity.name);

    const rename = async () => {
        if (renaming === null || !renaming.trim() || renaming.trim() === entity.name) {
            setRenaming(null);
            return;
        }
        setBusy(true);
        setActionError('');
        try {
            setEntity(await graphApi.renameEntity(entity.id, renaming.trim()));
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
            const merged = await graphApi.mergeEntity(entity.id, mergeTarget.id);
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
                        <button type="button" onClick={() => setRenaming(entity.name)} className="mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold text-muted hover:bg-chip hover:text-ink">이름 수정</button>
                    </div>
                )}
                {otherAliases.length > 0 && (
                    <p className="mt-1.5 text-[11.5px] leading-5 text-muted">
                        다른 표기: {otherAliases.join(', ')}
                    </p>
                )}
                {actionError && <p role="alert" className="mt-2 text-[11.5px] text-danger">{actionError}</p>}
                <button
                    type="button"
                    onClick={() => onFocus(entity.id)}
                    className="mt-3 h-8 w-full rounded-lg border border-line text-[12px] font-semibold hover:bg-chip"
                >
                    이 개체 중심으로 보기
                </button>
            </div>

            <Section title="관계" count={entity.relations.length}>
                {entity.relations.length === 0 && <p className="mb-2 text-[12px] text-muted">연결된 관계가 없습니다.</p>}
                <ul className="space-y-1.5">
                    {entity.relations.map((r) => (
                        <RelationRow
                            key={r.id}
                            relation={r}
                            perspectiveId={entity.id}
                            onOpenEntity={onOpenEntity}
                            onReplaced={changed}
                            onDeleted={changed}
                        />
                    ))}
                </ul>
                <div className="mt-2.5">
                    <AddRelationForm key={entity.id} entity={entity} onCreated={changed} requestPick={requestPick} />
                </div>
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

            <Section title="다른 개체와 합치기">
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
            </Section>
        </div>
    );
}

/** 엣지를 눌렀을 때: 관계 하나 편집 */
export function EdgePanel({
    relation,
    onOpenEntity,
    onReplaced,
    onDeleted,
}: {
    relation: GraphRelation;
    onOpenEntity: (id: number) => void;
    onReplaced: (relation: GraphRelation) => void;
    onDeleted: () => void;
}) {
    return (
        <div className="p-4">
            <p className="text-[11px] font-bold text-muted">관계</p>
            <h2 className="mt-1 text-[15px] font-bold">{RELATION_META[relation.type].label}</h2>
            <p className="mt-0.5 text-[11.5px] text-muted">{RELATION_META[relation.type].hint}</p>
            <ul className="mt-3">
                <RelationRow key={relation.id} relation={relation} onOpenEntity={onOpenEntity} onReplaced={onReplaced} onDeleted={onDeleted} />
            </ul>
            <p className="mt-3 text-[11.5px] leading-5 text-muted">
                문서에서 뽑은 관계를 고치거나 지우면, 그 문서를 다시 추출해도 원래 관계로 돌아가지 않습니다.
            </p>
        </div>
    );
}
