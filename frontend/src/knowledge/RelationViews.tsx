import { useState } from 'react';

import { linkProps } from '../lib/router';
import { reviewPath } from '../rag/api';
import { graphApi } from './api';
import { EntityPicker, TypeDot, type PickedEntity } from './EntityPicker';
import { errorText } from './errors';
import { allowedChoices, groupTitle, relationPhrase } from './relationPhrases';
import { groupRelations } from './relationGroups';
import { entityMeta, ruleWarning, useGraphSchema } from './schemaContext';
import type { EntityType, GraphRelation } from './types';

/**
 * 관계를 사람이 읽는 말로 보이고 고르는 화면 조각 (백엔드 변경 없음).
 * - RelationGroups: 개체 패널의 관계. 같은 뜻(관계 종류·방향)끼리 묶어 제목 한 줄 + 상대 개체 칩
 * - RelationDetail: 관계 하나를 문장으로, 근거, 바꾸기·지우기
 * - RelationChooser: 두 개체 사이의 관계 고르기 (그래프 선 잇기 창과 패널의 관계 추가가 같이 쓴다)
 * - AddRelation: 패널에서 관계 추가 (대상 찾기 → 관계 고르기)
 */

const chip = 'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[12px]';
const smallButton = 'h-7 rounded-md border border-line bg-white px-2 text-[11.5px] font-semibold hover:bg-chip disabled:opacity-50';

function evidenceOf(r: GraphRelation): string {
    if (r.origin === 'spec') return '사양 DB';
    if (r.origin === 'manual') return '사용자 입력';
    if (!r.original_name) return '근거 없음';
    return r.page !== null ? `${r.original_name} · ${r.page}쪽` : r.original_name;
}

/** 묶음 아래 한 줄: 어디서 찾은 관계인지 */
function sourceSummary(rows: GraphRelation[]): string {
    const files = [...new Set(rows.filter((r) => r.origin !== 'spec' && r.origin !== 'manual' && r.original_name).map((r) => r.original_name as string))];
    const parts: string[] = [];
    if (files.length) parts.push(`${files[0]}${files.length > 1 ? ` 외 문서 ${files.length - 1}개` : ''}에서 찾음`);
    if (rows.some((r) => r.origin === 'spec')) parts.push('사양 DB');
    if (rows.some((r) => r.origin === 'manual')) parts.push('사용자 입력');
    return parts.join(' · ');
}

/** 관계 하나(같은 출발·종류·도착의 출처 행 묶음)를 문장으로 보이고 바꾸기·지우기 */
export function RelationDetail({ rows, perspectiveId, onOpenEntity, onChanged }: {
    rows: GraphRelation[];
    /** 보고 있는 개체. 있으면 "상대 개체 열기"가 반대쪽을 연다 */
    perspectiveId?: number;
    onOpenEntity: (id: number) => void;
    onChanged: (relation?: GraphRelation) => void;
}) {
    const { schema } = useGraphSchema();
    const [mode, setMode] = useState<'' | 'change' | 'delete'>('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const relation = rows[0];
    const warning = ruleWarning(schema, relation.type, relation.source_type, relation.target_type);
    const run = async (action: () => Promise<GraphRelation | void>) => {
        setBusy(true); setError('');
        try { const result = await action(); setMode(''); onChanged(result ?? undefined); }
        catch (e) { setError(errorText(e)); } finally { setBusy(false); }
    };
    const removeAll = () => run(async () => {
        // 사람이 넣은 행은 하나씩 지우고, 자동 행(문서·사양 DB)은 하나만 지우면 서버가 그 관계의 모든 자동 출처를 제외한다
        for (const r of rows.filter((x) => x.origin === 'manual')) await graphApi.deleteRelation(r.id, r.revision, 'all');
        const auto = rows.find((x) => x.origin !== 'manual');
        if (auto) await graphApi.deleteRelation(auto.id, auto.revision, 'all');
    });
    return (
        <div className="rounded-lg border border-brand/30 bg-white p-2.5 text-[12px]">
            <p className="text-[12.5px] font-semibold leading-5">
                {relationPhrase(schema, relation.type, relation.source_name, relation.target_name)}
            </p>
            {warning && <p className="mt-1 rounded bg-warn-soft/60 px-1.5 py-0.5 text-[11px] text-ink/80" title="규칙은 문서 자동 추출만 거릅니다. 의도한 관계면 그대로 두세요">규칙과 다름: {warning}</p>}
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted">
                {rows.map((r) => (
                    <li key={r.id} className="truncate">근거: {r.file_id
                        ? <a {...linkProps(reviewPath(r.file_id))} className="hover:text-brand-hover hover:underline">{evidenceOf(r)}</a>
                        : evidenceOf(r)}</li>
                ))}
            </ul>
            {schema.editing_enabled && mode === '' && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                    <button type="button" className={smallButton} onClick={() => onOpenEntity(relation.source_id === perspectiveId ? relation.target_id : relation.source_id)}>
                        {relation.source_id === perspectiveId ? relation.target_name : relation.source_name} 열기</button>
                    <button type="button" className={smallButton} onClick={() => setMode('change')}>관계 바꾸기</button>
                    <button type="button" className={`${smallButton} text-danger`} onClick={() => setMode('delete')}>이 관계 지우기</button>
                </div>
            )}
            {mode === 'change' && (
                <div className="mt-2 space-y-1.5 rounded bg-surface p-2">
                    <p className="text-[11.5px] text-muted">바꿀 관계를 고르세요</p>
                    {schema.relation_types.filter((t) => t.active && t.key !== relation.type).map((t) => (
                        <button key={t.key} type="button" disabled={busy} className="block w-full rounded border border-line bg-white px-2 py-1 text-left hover:bg-chip"
                            onClick={() => void run(() => graphApi.updateRelation(relation.id, { type: t.key, expected_revision: relation.revision }))}>
                            {relationPhrase(schema, t.key, relation.source_name, relation.target_name)}
                        </button>
                    ))}
                    <button type="button" disabled={busy} className="block w-full rounded border border-line bg-white px-2 py-1 text-left hover:bg-chip"
                        onClick={() => void run(() => graphApi.updateRelation(relation.id, { reverse: true, expected_revision: relation.revision }))}>
                        방향을 뒤집어서: {relationPhrase(schema, relation.type, relation.target_name, relation.source_name)}
                    </button>
                    <button type="button" className={smallButton} onClick={() => setMode('')}>취소</button>
                </div>
            )}
            {mode === 'delete' && (
                <div className="mt-2 rounded border border-danger/30 bg-danger-surface/40 p-2">
                    <p className="text-[11.5px]">이 관계를 그래프에서 지웁니다. 문서를 다시 뽑아도 되살아나지 않고, 원본 문서·사양 DB는 그대로입니다.</p>
                    <div className="mt-1.5 flex gap-1.5">
                        <button type="button" disabled={busy} className="h-7 rounded-md bg-danger px-2 text-[11.5px] font-bold text-white disabled:opacity-50" onClick={() => void removeAll()}>지우기</button>
                        <button type="button" className={smallButton} onClick={() => setMode('')}>취소</button>
                    </div>
                </div>
            )}
            {error && <p role="alert" className="mt-1 text-[11px] text-danger">{error}</p>}
        </div>
    );
}

interface Group { key: string; type: string; outgoing: boolean; items: GraphRelation[][] }

/** 개체 패널의 관계: 같은 뜻(관계 종류·방향)끼리 묶어 제목 한 줄과 상대 개체 칩으로 보인다 */
export function RelationGroups({ entityId, relations, onOpenEntity, onChanged }: {
    entityId: number;
    relations: GraphRelation[];
    onOpenEntity: (id: number) => void;
    onChanged: () => void;
}) {
    const { schema } = useGraphSchema();
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const [selected, setSelected] = useState<string | null>(null);
    const groups = new Map<string, Group>();
    for (const rows of groupRelations(relations)) {
        const outgoing = rows[0].source_id === entityId;
        const key = `${rows[0].type}|${outgoing ? 'out' : 'in'}`;
        const group = groups.get(key) ?? { key, type: rows[0].type, outgoing, items: [] };
        group.items.push(rows);
        groups.set(key, group);
    }
    // 사양 값은 뒤로, 나머지는 많이 이어진 순서
    const ordered = [...groups.values()].sort((a, b) => Number(a.type === 'has_spec') - Number(b.type === 'has_spec') || b.items.length - a.items.length);
    if (!ordered.length) return <p className="text-[12px] text-muted">연결된 관계가 없습니다.</p>;
    return (
        <div className="space-y-2">
            {ordered.map((group) => {
                const others = group.items.map((rows) => (group.outgoing
                    ? { id: rows[0].target_id, type: rows[0].target_type, name: rows[0].target_name }
                    : { id: rows[0].source_id, type: rows[0].source_type, name: rows[0].source_name }));
                const limit = expanded.has(group.key) ? others.length : group.type === 'has_spec' ? 0 : 6;
                const selectedRows = group.items.find((rows) => `${group.key}|${rows[0].id}` === selected);
                return (
                    <div key={group.key} className="rounded-lg border border-divide bg-white p-2.5">
                        <p className="text-[12.5px] font-semibold">
                            {groupTitle(schema, group.type, group.outgoing, others.map((o) => o.type))}
                            <span className="ml-1 font-normal text-muted">{others.length}</span>
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted">{sourceSummary(group.items.flat())}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1">
                            {group.items.slice(0, limit).map((rows, i) => {
                                const key = `${group.key}|${rows[0].id}`;
                                const warn = ruleWarning(schema, rows[0].type, rows[0].source_type, rows[0].target_type);
                                return (
                                    <button key={key} type="button" aria-pressed={selected === key}
                                        onClick={() => setSelected(selected === key ? null : key)}
                                        className={`${chip} ${selected === key ? 'border-brand bg-brand-tint' : warn ? 'border-warn/60 bg-warn-soft/40' : 'border-line bg-white hover:bg-chip'}`}
                                        title={warn ? `규칙과 다름: ${warn}` : '누르면 관계를 봅니다'}>
                                        <TypeDot type={others[i].type} /><span className="truncate">{others[i].name}</span>
                                        {rows.length > 1 && <span className="text-[10.5px] text-muted">근거 {rows.length}</span>}
                                    </button>
                                );
                            })}
                            {others.length > limit && (
                                <button type="button" className="px-1 text-[12px] font-semibold text-brand-hover hover:underline"
                                    onClick={() => setExpanded(new Set(expanded).add(group.key))}>
                                    {limit === 0 ? `${others.length}개 펼치기` : `${others.length - limit}개 더 보기`}
                                </button>
                            )}
                        </div>
                        {selectedRows && <div className="mt-2"><RelationDetail rows={selectedRows} perspectiveId={entityId} onOpenEntity={onOpenEntity} onChanged={() => { setSelected(null); onChanged(); }} /></div>}
                    </div>
                );
            })}
        </div>
    );
}

export interface ChooserEntity { id?: number; type: EntityType; name: string }

/**
 * 두 개체 사이의 관계 고르기. 규칙에 맞는 관계만 문장으로 보이고 방향은 종류로 정한다.
 * "다른 관계…"를 열면 모든 관계 종류(두 방향)를 고를 수 있고, 만들면 서버가 경고를 붙인다.
 * b.id가 없으면 새 개체(b.type, b.name)를 만들며 잇는다.
 */
export function RelationChooser({ a, b, onCreated, onCancel }: {
    a: ChooserEntity & { id: number };
    b: ChooserEntity;
    onCreated: (relation: GraphRelation) => void;
    onCancel: () => void;
}) {
    const { schema } = useGraphSchema();
    const [showAll, setShowAll] = useState(false);
    const [memo, setMemo] = useState('');
    const [showMemo, setShowMemo] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const choices = allowedChoices(schema, a.type, b.type);
    const create = async (type: string, forward: boolean) => {
        setBusy(true); setError('');
        try {
            const source = memo.trim() ? { reason: memo.trim() } : undefined;
            const relation = b.id !== undefined
                ? await graphApi.createRelation(forward ? { source_id: a.id, type, target_id: b.id, source } : { source_id: b.id, type, target_id: a.id, source })
                : await graphApi.createRelation({ source_id: a.id, type, new_target: { type: b.type, name: b.name }, reverse: !forward, source });
            onCreated(relation);
        } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
    };
    const option = (key: string, type: string, forward: boolean) => (
        <button key={key} type="button" disabled={busy} onClick={() => void create(type, forward)}
            className="block w-full rounded-md border border-line bg-white px-2.5 py-1.5 text-left text-[12.5px] hover:border-brand hover:bg-brand-tint disabled:opacity-50">
            {forward ? relationPhrase(schema, type, a.name, b.name) : relationPhrase(schema, type, b.name, a.name)}
        </button>
    );
    return (
        <div className="space-y-1.5 text-[12px]">
            <p className="font-semibold">{a.name} — {b.name}{b.id === undefined && <span className="ml-1 font-normal text-brand-hover">(새 {entityMeta(schema, b.type).label})</span>}</p>
            <p className="text-muted">어떤 관계인가요?</p>
            {choices.length === 0 && <p className="rounded bg-warn-soft/50 px-2 py-1 text-ink/80">
                {entityMeta(schema, a.type).label}와(과) {entityMeta(schema, b.type).label} 사이에 정해진 관계가 없습니다.</p>}
            {choices.map((c) => option(`${c.definition.key}-${c.forward}`, c.definition.key, c.forward))}
            {showAll ? (
                <div className="space-y-1 rounded bg-surface p-1.5">
                    <p className="text-[11px] text-muted">규칙에 없는 연결도 만들 수 있습니다. 만들면 노란 경고가 붙습니다.</p>
                    {schema.relation_types.filter((t) => t.active).flatMap((t) => [option(`all-${t.key}-f`, t.key, true), option(`all-${t.key}-b`, t.key, false)])}
                </div>
            ) : (
                <button type="button" className="text-[11.5px] font-semibold text-muted hover:text-ink hover:underline" onClick={() => setShowAll(true)}>다른 관계…</button>
            )}
            {showMemo ? (
                <label className="block text-[11.5px] text-muted">메모 (근거·사유, 선택)
                    <textarea value={memo} onChange={(e) => setMemo(e.target.value)} maxLength={4000} rows={2} className="mt-0.5 w-full rounded border border-line p-1 text-[12px] text-ink" />
                </label>
            ) : (
                <button type="button" className="block text-[11.5px] font-semibold text-muted hover:text-ink hover:underline" onClick={() => setShowMemo(true)}>메모 추가 (선택)</button>
            )}
            {error && <p role="alert" className="text-[11.5px] text-danger">{error}</p>}
            <div className="flex justify-end"><button type="button" className={smallButton} onClick={onCancel}>취소</button></div>
        </div>
    );
}

/** 개체 패널에서 관계 추가: 대상 찾기(이름 또는 그래프에서 고르기) → 관계 고르기 */
export function AddRelation({ entity, onCreated, onPickFromGraph }: {
    entity: { id: number; type: EntityType; name: string };
    onCreated: (relation: GraphRelation) => void;
    onPickFromGraph: (done: (picked: PickedEntity) => void) => void;
}) {
    const [open, setOpen] = useState(false);
    const [target, setTarget] = useState<PickedEntity | null>(null);
    const [picking, setPicking] = useState(false);
    const [notice, setNotice] = useState('');
    const { schema } = useGraphSchema();
    if (!open) {
        return (
            <div>
                <button type="button" onClick={() => { setOpen(true); setNotice(''); }} className="h-8 w-full rounded-lg border border-dashed border-line text-[12px] font-semibold hover:bg-chip">+ 관계 추가</button>
                {notice && <p className="mt-1.5 rounded bg-warn-soft/50 px-2 py-1 text-[11.5px] text-ink/80">{notice}</p>}
            </div>
        );
    }
    const close = () => { setOpen(false); setTarget(null); setPicking(false); };
    return (
        <div className="rounded-lg border border-brand/30 bg-surface p-2.5">
            {target ? (
                <RelationChooser a={entity} b={target.kind === 'existing' ? { id: target.id, type: target.type, name: target.name } : { type: target.type, name: target.name }}
                    onCancel={() => setTarget(null)}
                    onCreated={(relation) => {
                        close();
                        setNotice(relation.warnings?.length ? `만들었습니다. ${relation.warnings.join(' ')}`
                            : `만들었습니다: ${relationPhrase(schema, relation.type, relation.source_name, relation.target_name)}`);
                        onCreated(relation);
                    }} />
            ) : (
                <div className="space-y-1.5">
                    <p className="text-[12px] font-semibold">무엇과 연결할까요?</p>
                    <div className="flex gap-1.5">
                        <div className="min-w-0 flex-1"><EntityPicker label="연결할 개체" placeholder="이름으로 찾기" excludeId={entity.id} allowCreate onPick={setTarget} /></div>
                        <button type="button" aria-pressed={picking} onClick={() => { setPicking(true); onPickFromGraph((picked) => { setPicking(false); setTarget(picked); }); }}
                            className={`h-9 shrink-0 rounded-lg border px-2 text-[11.5px] font-semibold ${picking ? 'border-brand bg-brand-tint text-brand-hover' : 'border-line bg-white hover:bg-chip'}`}>
                            {picking ? '노드를 누르세요' : '그래프에서 고르기'}
                        </button>
                    </div>
                    <p className="text-[11px] text-muted">그래프 위의 "선 잇기"를 켜고 노드를 차례로 눌러도 연결할 수 있습니다.</p>
                    <div className="flex justify-end"><button type="button" className={smallButton} onClick={close}>닫기</button></div>
                </div>
            )}
        </div>
    );
}
