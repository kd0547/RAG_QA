import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AppHeader } from '../components/AppHeader';
import { ApiError } from '../lib/http';
import { ragApi } from '../rag/api';
import type { FileSummary } from '../rag/types';
import { graphApi } from './api';
import { EntityPicker, TypeDot } from './EntityPicker';
import { EdgePanel, EntityPanel, type RequestPick } from './EntityPanel';
import { errorText } from './errors';
import { GraphCanvas, type Selection } from './GraphCanvas';
import { layoutGraph, layoutHierarchy, type Point } from './layout';
import { GraphSchemaProvider } from './schema';
import { GraphEditingToolbar } from './GraphEditing';
import { MergeConfirm, type MergeDone } from './MergeViews';
import { RelationChooser } from './RelationViews';
import { relationPhrase } from './relationPhrases';
import { ORIGIN_META } from './meta';
import { entityMeta, typeKeys, useGraphSchema } from './schemaContext';
import type { EntityType, GraphEdge, GraphNode, GraphRelation, GraphStats, GraphView, RelationOrigin } from './types';

/**
 * 지식 그래프 (/knowledge?entity=…&depth=…)
 *
 * 문서에서 뽑은 제품·부품·인증 관계를 그림으로 보고 고친다. 에이전트의 graph_search가 이 그래프를 쓴다.
 * - 노드를 누르면 오른쪽에 상세·관계 편집이 열린다. 엣지를 누르면 그 관계만 편집한다.
 * - 노드는 끌어서 옮길 수 있고, 배경을 끌면 화면이 움직이고, 휠로 확대·축소한다.
 * 백엔드: app/routers/graph.py
 */

const OVERVIEW_LIMIT = 150;
const FOCUS_LIMIT = 200;

function readUrl(): { entityId: number | null; depth: number } {
    const params = new URLSearchParams(window.location.search);
    const id = Number(params.get('entity'));
    const depth = Number(params.get('depth'));
    return { entityId: Number.isInteger(id) && id > 0 ? id : null, depth: depth >= 1 && depth <= 3 ? depth : 1 };
}

function writeUrl(entityId: number | null, depth: number) {
    const params = new URLSearchParams();
    if (entityId !== null) {
        params.set('entity', String(entityId));
        if (depth !== 1) params.set('depth', String(depth));
    }
    const search = params.toString();
    window.history.replaceState(null, '', `/knowledge${search ? `?${search}` : ''}`);
}

/** 노드 하나를 펼칠 때 부르는 보기: 바로 이웃 전부 (사양 값 노드 포함, 노드마다 최대 300개) */
function expandQuery(id: number) {
    return { entityId: id, depth: 1, limit: 300, specValues: 'all' as const, hideIsolatedSpec: false };
}

/** 한 번 펼칠 때 더하는 이웃 수. "더 보기"마다 이만큼 늘린다 */
const EXPAND_STEP = 20;

interface Expansion { view: GraphView; shown: number }

/** 펼친 노드의 이웃 순서: 이미 보이는 노드 → 사양 값이 아닌 관계(부품·인증·문서 등) → 사양 값. 같은 순위는 이름순 */
function orderedNeighbors(centerId: number, view: GraphView, visible: Set<number>): GraphNode[] {
    const viaSpec = new Set(view.edges.filter((e) => e.type === 'has_spec').flatMap((e) => [e.source, e.target]));
    const rank = (n: GraphNode) => (visible.has(n.id) ? 0 : n.type === 'spec_value' || viaSpec.has(n.id) ? 2 : 1);
    return view.nodes.filter((n) => n.id !== centerId)
        .sort((x, y) => rank(x) - rank(y) || x.name.localeCompare(y.name, 'ko'));
}

/** 기본 보기와 펼친 노드의 이웃을 합친다 (펼친 노드마다 shown개까지). 같은 노드·관계는 한 번만 */
function mergeViews(base: GraphView | null, expansions: Map<number, Expansion>): GraphView | null {
    if (!base || expansions.size === 0) return base;
    const nodes = new Map(base.nodes.map((n) => [n.id, n]));
    const pool = new Map<number, GraphEdge>(base.edges.map((e) => [e.id, e]));
    for (const [centerId, { view, shown }] of expansions) {
        const center = view.nodes.find((n) => n.id === centerId);
        if (center && !nodes.has(centerId)) nodes.set(centerId, center);
        for (const n of orderedNeighbors(centerId, view, new Set(nodes.keys())).slice(0, shown)) {
            if (!nodes.has(n.id)) nodes.set(n.id, n);
        }
        for (const e of view.edges) pool.set(e.id, e);
    }
    const edges = [...pool.values()].filter((e) => nodes.has(e.source) && nodes.has(e.target));
    return { nodes: [...nodes.values()], edges, truncated: base.truncated };
}

/** 펼쳐서 새로 나온 노드를 펼친 노드 둘레에 원형으로 놓는다 (덩어리로 섞이지 않게). 많으면 바깥 원을 더 쓴다 */
function ringPositions(center: Point, ids: number[], start: number): Map<number, Point> {
    const result = new Map<number, Point>();
    let placed = 0;
    let ring = 0;
    while (placed < ids.length) {
        const capacity = 10 + ring * 8;
        const count = Math.min(capacity, ids.length - placed);
        const radius = 120 + ring * 70;
        for (let i = 0; i < count; i++) {
            const angle = start + (i / count) * Math.PI * 2 + ring * 0.3;
            result.set(ids[placed + i], { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius });
        }
        placed += count;
        ring += 1;
    }
    return result;
}

export function KnowledgeSection() {
    return <GraphSchemaProvider><KnowledgeContent /></GraphSchemaProvider>;
}

function KnowledgeContent() {
    const { schema } = useGraphSchema();
    const [initial] = useState(readUrl);
    const [focusId, setFocusId] = useState<number | null>(initial.entityId);
    const [depth, setDepth] = useState(initial.depth);
    const [types, setTypes] = useState<EntityType[]>([]);
    const [fileId, setFileId] = useState('');
    const [files, setFiles] = useState<FileSummary[]>([]);

    const [baseData, setData] = useState<GraphView | null>(null);
    // 그래프에서 펼친 노드: 노드 id → 그 노드의 이웃 (GET /graph/view?entity_id=…&depth=1, 사양 값 포함)과 보이는 수
    const [expansions, setExpansions] = useState<Map<number, Expansion>>(new Map());
    const expansionsRef = useRef(expansions);
    useEffect(() => { expansionsRef.current = expansions; }, [expansions]);
    // 화면에 그리는 그래프 = 기본 보기 + 펼친 노드의 이웃
    const data = useMemo(() => mergeViews(baseData, expansions), [baseData, expansions]);
    const [loadError, setLoadError] = useState('');
    const [positions, setPositions] = useState<Map<number, Point>>(new Map());
    const [fitKey, setFitKey] = useState(0);
    const [selection, setSelection] = useState<Selection>(initial.entityId ? { kind: 'node', id: initial.entityId } : null);
    const [reloadKey, setReloadKey] = useState(0);
    const [panelVersion, setPanelVersion] = useState(0);
    const [stats, setStats] = useState<GraphStats | null>(null);
    const [picking, setPicking] = useState(false);
    const [rebuildState, setRebuildState] = useState<'idle' | 'confirm' | 'sent'>('idle');
    // 사양 값 노드는 고른 노드의 이웃으로만, 관계 없는 사양 노드 숨기기 (둘 다 기본 켬, 지시서 GR4-8)
    const [valuesNearOnly, setValuesNearOnly] = useState(true);
    const [hideIsolatedSpec, setHideIsolatedSpec] = useState(true);
    // 선 잇기: 켜면 노드를 누를 때 선이 포인터를 따라오고, 두 번째 노드를 누르면 관계를 고르는 창이 뜬다
    const [connectMode, setConnectMode] = useState(false);
    const [connecting, setConnecting] = useState<{ fromId: number; toId: number; x: number; y: number } | null>(null);
    const [connectNotice, setConnectNotice] = useState('');
    // 끌어다 놓아 합치기: 끈 노드, 놓은 노드, 확인 창 자리, 끌기 전 위치 (취소하면 되돌린다)
    const [merging, setMerging] = useState<{ draggedId: number; targetId: number; x: number; y: number; origin?: Point } | null>(null);
    const mainRef = useRef<HTMLElement>(null);
    // 계층 보기: null이면 자동 (중심 개체가 제품군이면 켬)
    const [treeChoice, setTreeChoice] = useState<boolean | null>(null);

    const positionsRef = useRef(positions);
    const pinnedRef = useRef(new Set<number>());
    const pickCallback = useRef<((node: GraphNode) => void) | null>(null);
    // 보는 범위가 바뀌면 화면을 다시 맞추고, 편집 뒤 다시 불러올 때는 그대로 둔다
    const queryKey = `${focusId}|${depth}|${types.join(',')}|${fileId}|${valuesNearOnly}|${hideIsolatedSpec}`;
    const lastQueryKey = useRef('');

    useEffect(() => {
        positionsRef.current = positions;
    }, [positions]);

    useEffect(() => {
        writeUrl(focusId, depth);
    }, [focusId, depth]);

    useEffect(() => {
        ragApi.listFiles().then(setFiles).catch(() => setFiles([]));
    }, []);

    useEffect(() => {
        graphApi.stats().then(setStats).catch(() => setStats(null));
    }, [reloadKey]);

    useEffect(() => {
        let ignore = false;
        const specOptions = { specValues: valuesNearOnly ? 'neighbors' as const : 'all' as const, hideIsolatedSpec };
        graphApi.view(focusId !== null
            ? { entityId: focusId, depth, types, limit: FOCUS_LIMIT, ...specOptions }
            : { types, fileId: fileId || null, limit: OVERVIEW_LIMIT, ...specOptions },
        ).then((view) => {
            if (ignore) return;
            const queryChanged = lastQueryKey.current !== queryKey;
            lastQueryKey.current = queryKey;
            const ids = view.nodes.map((n) => n.id);
            const previous = queryChanged ? new Map<number, Point>() : positionsRef.current;
            if (queryChanged) {
                pinnedRef.current = new Set();
                setExpansions(new Map());
            }
            const base = layoutGraph(ids, view.edges, previous, pinnedRef.current);
            const center = view.nodes.find((n) => n.id === focusId);
            const tree = treeChoice ?? center?.type === 'product_line';
            setPositions(tree && queryChanged ? layoutHierarchy(ids, view.edges, base, pinnedRef.current) : base);
            setData(view);
            setLoadError('');
            if (queryChanged) setFitKey((k) => k + 1);
        }).catch((e: unknown) => {
            if (ignore) return;
            // 중심으로 보던 개체가 없어졌으면 (합치기·정리로 삭제) 전체 보기로 돌아간다
            if (e instanceof ApiError && e.status === 404 && focusId !== null) {
                setFocusId(null);
                setSelection(null);
                return;
            }
            setLoadError(errorText(e));
        });
        return () => { ignore = true; };
        // queryKey가 focusId·depth·types·fileId를 모두 담는다
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [queryKey, reloadKey]);

    // Esc: 그래프에서 고르기 취소
    useEffect(() => {
        if (!picking) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                pickCallback.current = null;
                setPicking(false);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [picking]);

    const changed = useCallback(() => {
        setReloadKey((k) => k + 1);
        setPanelVersion((v) => v + 1);
    }, []);

    const requestPick: RequestPick = useCallback((onPicked) => {
        pickCallback.current = onPicked;
        setPicking(true);
    }, []);

    const nodeById = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

    /** 그래프 위 확인 창 자리: 누른 곳 근처, 그래프 영역 안 */
    const popupAt = (clientX: number, clientY: number, height: number) => {
        const box = mainRef.current?.getBoundingClientRect();
        const width = box?.width ?? 600;
        const boxHeight = box?.height ?? 600;
        return {
            x: Math.min(Math.max((clientX - (box?.left ?? 0)) + 12, 8), Math.max(8, width - 310)),
            y: Math.min(Math.max((clientY - (box?.top ?? 0)) - 20, 8), Math.max(8, boxHeight - height)),
        };
    };
    const canMerge = useCallback((draggedId: number, targetId: number) => (
        schema.editing_enabled && nodeById.get(draggedId)?.type === nodeById.get(targetId)?.type
    ), [schema.editing_enabled, nodeById]);
    const cancelMerge = useCallback(() => {
        const origin = merging?.origin;
        if (merging && origin) setPositions((prev) => new Map(prev).set(merging.draggedId, origin));
        setMerging(null);
    }, [merging]);
    useEffect(() => {
        if (!merging) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancelMerge(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [merging, cancelMerge]);
    /** 합친 뒤: 없어진 개체를 보던 곳은 남은 개체로 바꾼다 */
    const afterMerge = (done: MergeDone) => {
        setMerging(null);
        setConnecting(null);
        setConnectNotice(done.notice);
        if (focusId === done.sourceId) setFocusId(done.targetId);
        setSelection({ kind: 'node', id: done.targetId });
        changed();
    };

    // 펼쳐서 새로 나온 노드만 자리를 잡는다: 펼친 노드 둘레 원형. 이미 있는 노드는 움직이지 않는다
    useEffect(() => {
        if (!data) return;
        const current = positionsRef.current;
        const missing = new Set(data.nodes.filter((n) => !current.has(n.id)).map((n) => n.id));
        if (!missing.size) return;
        const next = new Map(current);
        for (const [centerId, { view }] of expansionsRef.current) {
            const center = next.get(centerId);
            if (!center) continue;
            const ids = view.nodes.map((n) => n.id).filter((id) => missing.has(id));
            const placedAround = view.nodes.filter((n) => n.id !== centerId && next.has(n.id)).length;
            ringPositions(center, ids, placedAround * 0.4).forEach((p, id) => { next.set(id, p); missing.delete(id); });
        }
        if (missing.size) {
            const fixed = new Set([...pinnedRef.current, ...next.keys()]);
            setPositions(layoutGraph(data.nodes.map((n) => n.id), data.edges, next, fixed));
        } else {
            setPositions(next);
        }
        setFitKey((k) => k + 1); // 펼친 이웃까지 보이게 화면을 맞춘다
    }, [data]);

    // 편집 뒤 다시 불러올 때 펼친 노드의 이웃도 새로 읽는다
    useEffect(() => {
        const ids = [...expansionsRef.current.keys()];
        if (!ids.length) return;
        let ignore = false;
        Promise.all(ids.map((id) => graphApi.view(expandQuery(id))
            .then((view) => [id, { view, shown: expansionsRef.current.get(id)?.shown ?? EXPAND_STEP }] as const).catch(() => null)))
            .then((results) => {
                if (ignore) return;
                setExpansions(new Map(results.filter((r): r is readonly [number, Expansion] => r !== null)));
            });
        return () => { ignore = true; };
    }, [reloadKey]);

    const [expandError, setExpandError] = useState('');
    const toggleExpand = useCallback((id: number) => {
        setExpandError('');
        if (expansionsRef.current.has(id)) {
            setExpansions((prev) => {
                const next = new Map(prev);
                next.delete(id);
                return next;
            });
            return;
        }
        graphApi.view(expandQuery(id))
            .then((view) => setExpansions((prev) => new Map(prev).set(id, { view, shown: EXPAND_STEP })))
            .catch((e: unknown) => setExpandError(errorText(e)));
    }, []);
    const showMore = (id: number) => setExpansions((prev) => {
        const item = prev.get(id);
        return item ? new Map(prev).set(id, { ...item, shown: item.shown + EXPAND_STEP }) : prev;
    });
    const expandedIds = useMemo(() => new Set(expansions.keys()), [expansions]);
    // 다 보이지 않은 펼친 노드: 이름, 전체 이웃 수, 보이는 이웃 수
    const partialExpansions = [...expansions].map(([id, { view, shown }]) => ({
        id, name: view.nodes.find((n) => n.id === id)?.name ?? `#${id}`, total: view.nodes.length - 1, shown,
    })).filter((x) => x.total > x.shown);
    const treeOn = treeChoice ?? (focusId !== null && nodeById.get(focusId)?.type === 'product_line');
    const hasTree = (data?.edges ?? []).some((e) => e.type === 'variant_of');
    const toggleTree = () => {
        const next = !treeOn;
        setTreeChoice(next);
        if (!data) return;
        const ids = data.nodes.map((n) => n.id);
        setPositions((prev) => (next ? layoutHierarchy(ids, data.edges, prev, pinnedRef.current) : layoutGraph(ids, data.edges, new Map(), pinnedRef.current)));
        setFitKey((k) => k + 1);
    };

    const focus = (id: number | null) => {
        setFocusId(id);
        if (id !== null) setSelection({ kind: 'node', id });
    };

    const toRelation = useCallback((edge: GraphEdge): GraphRelation | null => {
        const source = nodeById.get(edge.source);
        const target = nodeById.get(edge.target);
        if (!source || !target) return null;
        return {
            id: edge.id, revision: edge.revision, type: edge.type, origin: edge.origin, page: edge.page, file_id: edge.file_id, original_name: edge.original_name,
            source_id: source.id, source_type: source.type, source_name: source.name,
            target_id: target.id, target_type: target.type, target_name: target.name,
        };
    }, [nodeById]);
    const selectedEdge: GraphRelation | null = useMemo(() => {
        if (selection?.kind !== 'edge' || !data) return null;
        const edge = data.edges.find((e) => e.id === selection.id);
        return edge ? toRelation(edge) : null;
    }, [selection, data, toRelation]);
    // 고른 선과 같은 관계(출발·종류·도착)의 다른 출처 행
    const selectedSiblings: GraphRelation[] = useMemo(() => {
        if (!selectedEdge || !data) return [];
        return data.edges
            .filter((e) => e.id !== selectedEdge.id && e.source === selectedEdge.source_id && e.target === selectedEdge.target_id && e.type === selectedEdge.type)
            .map(toRelation).filter((r): r is GraphRelation => r !== null);
    }, [selectedEdge, data, toRelation]);

    const toggleType = (type: EntityType) => {
        setTypes((list) => (list.includes(type) ? list.filter((t) => t !== type) : [...list, type].sort()));
    };

    const totalEntities = stats ? Object.values(stats.entities).reduce<number>((a, b) => a + (b ?? 0), 0) : null;
    const isEmpty = data !== null && data.nodes.length === 0;
    const focusNode = focusId !== null ? nodeById.get(focusId) : undefined;

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader
                current="knowledge"
                aside={stats && (
                    <span className="hidden lg:block text-[11.5px] text-muted">
                        개체 {totalEntities} · 관계 {stats.relations}
                        {!!stats.relations_by_origin.manual && <> · 담당자 {stats.relations_by_origin.manual}</>}
                        {!!stats.blocked_relations && <> · 지운 관계 {stats.blocked_relations}</>}
                        {' '}· 문서 {stats.indexed_files}
                    </span>
                )}
            >
                <span className="hidden sm:block text-[12px] text-muted truncate">문서에서 뽑은 제품·부품·인증 관계</span>
            </AppHeader>
            <GraphEditingToolbar onChanged={changed} onSelect={focus} />

            <div className="flex-1 min-h-0 flex flex-col md:flex-row">
                <main ref={mainRef} className="relative flex-1 min-w-0 min-h-[480px] bg-surface">
                    {/* 도구 모음 */}
                    <div className="absolute left-3 right-3 top-3 z-10 flex flex-wrap items-start gap-2 pointer-events-none">
                        <div className="pointer-events-auto w-full sm:w-64">
                            <EntityPicker label="개체 찾기" placeholder="개체 찾기 (예: N5800, KC 인증)" onPick={(p) => { if (p.kind === 'existing') focus(p.id); }} />
                        </div>
                        {focusId !== null ? (
                            <div className="pointer-events-auto flex h-9 items-center gap-1.5 rounded-lg border border-brand/25 bg-white pl-2.5 pr-1 shadow-[0_1px_3px_rgba(20,28,43,0.06)]">
                                <span className="max-w-[160px] truncate text-[12px] font-semibold">
                                    {focusNode ? focusNode.name : `#${focusId}`} 중심
                                </span>
                                <select
                                    aria-label="몇 단계까지 볼지"
                                    value={depth}
                                    onChange={(e) => setDepth(Number(e.target.value))}
                                    className="h-7 rounded-md border border-line bg-white px-1 text-[11.5px]"
                                >
                                    {[1, 2, 3].map((d) => <option key={d} value={d}>{d}단계</option>)}
                                </select>
                                <button type="button" onClick={() => setFocusId(null)} className="h-7 rounded-md px-2 text-[11.5px] font-semibold text-muted hover:bg-chip hover:text-ink">
                                    전체 보기
                                </button>
                            </div>
                        ) : (
                            <select
                                aria-label="문서로 거르기"
                                value={fileId}
                                onChange={(e) => setFileId(e.target.value)}
                                className="pointer-events-auto h-9 max-w-[220px] rounded-lg border border-line bg-white px-2 text-[12px]"
                            >
                                <option value="">모든 문서</option>
                                {files.map((f) => <option key={f.file_id} value={f.file_id}>{f.original_name}</option>)}
                            </select>
                        )}
                        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-lg border border-line bg-white px-2 py-1 text-[11.5px]">
                            {expansions.size > 0 && <button type="button" onClick={() => setExpansions(new Map())}
                                className="h-6 rounded-md px-2 font-semibold hover:bg-chip">펼친 것 모두 접기 ({expansions.size})</button>}
                            {expandError && <span role="alert" className="text-danger">{expandError}</span>}
                            {partialExpansions.map((x) => (
                                <span key={x.id} className="flex items-center gap-1 text-muted">
                                    {x.name}: 이웃 {x.total}개 중 {x.shown}개
                                    <button type="button" onClick={() => showMore(x.id)} className="h-6 rounded-md px-1.5 font-semibold text-ink hover:bg-chip">{EXPAND_STEP}개 더</button>
                                </span>
                            ))}
                            {schema.editing_enabled && <button type="button" aria-pressed={connectMode}
                                onClick={() => { setConnectMode(!connectMode); setConnecting(null); setConnectNotice(''); }}
                                title="켜면 노드를 누를 때 선이 마우스를 따라오고, 이을 노드를 누르면 관계를 고릅니다"
                                className={`h-6 rounded-md px-2 font-semibold ${connectMode ? 'bg-brand text-white' : 'hover:bg-chip'}`}>선 잇기</button>}
                            {hasTree && <button type="button" aria-pressed={treeOn} onClick={toggleTree}
                                className={`h-6 rounded-md px-2 font-semibold ${treeOn ? 'bg-ink text-white' : 'hover:bg-chip'}`}>계층 보기</button>}
                            <label className="flex items-center gap-1"><input type="checkbox" checked={valuesNearOnly} onChange={(e) => setValuesNearOnly(e.target.checked)} /> 사양 값은 이웃만</label>
                            <label className="flex items-center gap-1"><input type="checkbox" checked={hideIsolatedSpec} onChange={(e) => setHideIsolatedSpec(e.target.checked)} /> 관계 없는 사양 노드 숨기기</label>
                        </div>
                        <div role="group" aria-label="개체 종류 거르기" className="pointer-events-auto flex flex-wrap gap-1">
                            {typeKeys(schema, true).map((t) => {
                                const active = types.includes(t);
                                const meta = entityMeta(schema, t);
                                return (
                                    <button
                                        key={t}
                                        type="button"
                                        aria-pressed={active}
                                        onClick={() => toggleType(t)}
                                        title={meta.hint}
                                        className={`flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-semibold transition-colors ${active ? 'border-ink bg-ink text-white' : 'border-line bg-white text-ink/75 hover:bg-chip'}`}
                                    >
                                        <TypeDot type={t} className="w-2 h-2 ring-1 ring-white/70" />
                                        {meta.label}
                                        {stats?.entities[t] !== undefined && <span className={active ? 'text-white/70' : 'text-muted'}>{stats.entities[t]}</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {connectMode && !connecting && (
                        <div className="pointer-events-none absolute bottom-14 left-1/2 z-20 max-w-[92%] -translate-x-1/2 rounded-full bg-brand px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-lg">
                            선 잇기: 노드를 누르면 선이 따라옵니다. 이을 노드를 누르세요 · 빈 곳이나 Esc로 취소
                        </div>
                    )}
                    {merging && (
                        <div role="dialog" aria-label="같은 개체로 합치기"
                            className="absolute z-30 w-[300px] max-h-[70%] overflow-y-auto rounded-xl border border-line bg-white p-3 shadow-xl"
                            style={{ left: merging.x, top: merging.y }}>
                            <MergeConfirm key={`${merging.draggedId}-${merging.targetId}`} aId={merging.draggedId} bId={merging.targetId}
                                onCancel={cancelMerge} onMerged={afterMerge} />
                        </div>
                    )}
                    {connectNotice && !connecting && !merging && (
                        <div role="status" className="absolute bottom-14 left-1/2 z-20 max-w-[90%] -translate-x-1/2 rounded-lg border border-line bg-white px-3 py-1.5 text-[12px] shadow-lg">
                            {connectNotice}
                            <button type="button" onClick={() => setConnectNotice('')} aria-label="알림 닫기" className="ml-2 text-muted hover:text-ink">×</button>
                        </div>
                    )}
                    {connecting && nodeById.get(connecting.fromId) && nodeById.get(connecting.toId) && (
                        <div className="absolute z-30 w-[300px] max-h-[70%] overflow-y-auto rounded-xl border border-line bg-white p-3 shadow-xl"
                            style={{ left: connecting.x, top: connecting.y }}>
                            <RelationChooser
                                a={nodeById.get(connecting.fromId)!}
                                b={nodeById.get(connecting.toId)!}
                                onCancel={() => setConnecting(null)}
                                onCreated={(relation) => {
                                    setConnecting(null);
                                    setConnectNotice(relation.warnings?.length
                                        ? `연결했습니다. ${relation.warnings.join(' ')}`
                                        : `연결했습니다: ${relationPhrase(schema, relation.type, relation.source_name, relation.target_name)}`);
                                    changed();
                                }}
                            />
                        </div>
                    )}
                    {picking && (
                        <div className="absolute left-1/2 top-16 z-20 -translate-x-1/2 rounded-full bg-ink px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-lg">
                            고를 노드를 누르세요 · Esc로 취소
                        </div>
                    )}

                    {loadError ? (
                        <div className="flex h-full items-center justify-center p-6">
                            <div role="alert" className="max-w-md rounded-xl border border-danger/20 bg-danger-surface px-4 py-3 text-[13px] text-danger">
                                {loadError}
                                <button type="button" onClick={() => setReloadKey((k) => k + 1)} className="ml-3 font-semibold underline">다시 시도</button>
                            </div>
                        </div>
                    ) : data === null ? (
                        <p className="flex h-full items-center justify-center text-[13px] text-muted">그래프를 불러오는 중…</p>
                    ) : isEmpty ? (
                        <div className="flex h-full items-center justify-center p-6">
                            <div className="max-w-md rounded-2xl border border-divide bg-white p-6 text-center">
                                <h2 className="text-[15px] font-bold">{types.length || fileId || focusId !== null ? '조건에 맞는 개체가 없습니다' : '아직 그래프가 없습니다'}</h2>
                                <p className="mt-2 text-[12.5px] leading-6 text-muted">
                                    파일을 올리면 페이지마다 개체와 관계를 자동으로 뽑습니다. 이미 올린 문서는 아래 버튼으로 한 번에 뽑을 수 있습니다.
                                    페이지마다 LLM을 불러 문서 양에 따라 수십 분 걸릴 수 있습니다.
                                </p>
                                {rebuildState === 'sent' ? (
                                    <p className="mt-4 text-[12.5px] font-semibold text-brand-hover">추출을 시작했습니다. 잠시 뒤 새로고침하세요.</p>
                                ) : rebuildState === 'confirm' ? (
                                    <div className="mt-4 flex justify-center gap-2">
                                        <button type="button" onClick={() => setRebuildState('idle')} className="h-9 rounded-lg px-3 text-[12px] font-semibold text-muted hover:bg-chip">취소</button>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                graphApi.rebuild().then(() => setRebuildState('sent')).catch((e: unknown) => {
                                                    setRebuildState('idle');
                                                    setLoadError(errorText(e));
                                                });
                                            }}
                                            className="h-9 rounded-lg bg-brand px-3 text-[12px] font-bold text-white hover:bg-brand-hover"
                                        >
                                            모든 문서 추출 시작
                                        </button>
                                    </div>
                                ) : (
                                    <button type="button" onClick={() => setRebuildState('confirm')} className="mt-4 h-9 rounded-lg border border-line px-3 text-[12px] font-semibold hover:bg-chip">
                                        올린 문서에서 그래프 만들기
                                    </button>
                                )}
                            </div>
                        </div>
                    ) : (
                        <GraphCanvas
                            nodes={data.nodes}
                            edges={data.edges}
                            positions={positions}
                            selection={selection}
                            picking={picking}
                            fitKey={fitKey}
                            onSelect={setSelection}
                            onPick={(id) => {
                                const node = nodeById.get(id);
                                const callback = pickCallback.current;
                                pickCallback.current = null;
                                setPicking(false);
                                if (node && callback) callback(node);
                            }}
                            expandedIds={expandedIds}
                            onToggleExpand={toggleExpand}
                            connectMode={connectMode}
                            onConnect={(fromId, toId, clientX, clientY) => {
                                setConnectNotice('');
                                setConnecting({ fromId, toId, ...popupAt(clientX, clientY, 320) });
                            }}
                            canMerge={canMerge}
                            onMergeDrop={(draggedId, targetId, clientX, clientY, origin) => {
                                setConnectNotice('');
                                setConnecting(null);
                                setMerging({ draggedId, targetId, origin, ...popupAt(clientX, clientY, 330) });
                            }}
                            onMoveNode={(id, p) => {
                                pinnedRef.current.add(id);
                                setPositions((prev) => new Map(prev).set(id, p));
                            }}
                        />
                    )}

                    {/* 범례 */}
                    {data && !isEmpty && (
                        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-divide bg-white/90 px-2.5 py-1.5 text-[11px] text-muted">
                            {(Object.keys(ORIGIN_META) as RelationOrigin[]).filter((o) => o !== 'seed').map((origin) => (
                                <span key={origin} className="flex items-center gap-1.5">
                                    <svg width="22" height="6" aria-hidden>
                                        <line x1="0" y1="3" x2="22" y2="3" stroke={ORIGIN_META[origin].stroke} strokeWidth="2" strokeDasharray={ORIGIN_META[origin].dash} />
                                    </svg>
                                    {ORIGIN_META[origin].label}
                                </span>
                            ))}
                            <span>· 개체 {data.nodes.length} · 관계 {data.edges.length}{data.truncated && ' (일부만 표시)'}</span>
                            <span>· 노드를 두 번 누르거나 +숫자를 누르면 숨은 이웃을 펼칩니다</span>
                        </div>
                    )}
                </main>

                <aside aria-label="선택한 개체" className="md:w-[360px] shrink-0 border-t md:border-t-0 md:border-l border-divide bg-white md:overflow-y-auto">
                    {selection?.kind === 'node' ? (
                        <EntityPanel
                            key={selection.id}
                            entityId={selection.id}
                            version={panelVersion}
                            onOpenEntity={(id) => setSelection({ kind: 'node', id })}
                            onFocus={focus}
                            onChanged={changed}
                            onMerged={(sourceId, targetId, notice) => {
                                if (focusId === sourceId) setFocusId(targetId || null);
                                setSelection(targetId ? { kind: 'node', id: targetId } : null);
                                if (notice) setConnectNotice(notice);
                                changed();
                            }}
                            requestPick={requestPick}
                        />
                    ) : selectedEdge ? (
                        <EdgePanel
                            relation={selectedEdge}
                            siblings={selectedSiblings}
                            onOpenEntity={(id) => setSelection({ kind: 'node', id })}
                            onReplaced={(r) => {
                                setSelection({ kind: 'edge', id: r.id });
                                changed();
                            }}
                            onDeleted={() => {
                                setSelection(null);
                                changed();
                            }}
                        />
                    ) : (
                        <div className="p-5 text-[12.5px] leading-6 text-muted">
                            <h2 className="text-[14px] font-bold text-ink">개체를 고르세요</h2>
                            <ul className="mt-2 list-disc space-y-1 pl-4">
                                <li>노드를 누르면 관계를 고치거나 추가할 수 있습니다.</li>
                                <li>선을 누르면 그 관계만 고칩니다.</li>
                                <li>노드는 끌어서 옮기고, 휠로 확대·축소합니다.</li>
                                {schema.editing_enabled && <li>같은 대상이 둘로 나뉘어 있으면 한 노드를 같은 종류의 노드 위로 끌어다 놓아 합칩니다.</li>}
                                <li>사람이 고친 관계는 문서를 다시 추출해도 유지됩니다.</li>
                            </ul>
                            <div className="mt-4 grid grid-cols-2 gap-1.5">
                                {typeKeys(schema, true).map((t) => (
                                    <span key={t} className="flex items-center gap-1.5 text-[11.5px]">
                                        <TypeDot type={t} />
                                        <span className="text-ink/80">{entityMeta(schema, t).label}</span>
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </aside>
            </div>
        </div>
    );
}
