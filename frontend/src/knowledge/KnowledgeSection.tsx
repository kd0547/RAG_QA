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
import { layoutGraph, type Point } from './layout';
import { ENTITY_META, ENTITY_TYPES, ORIGIN_META } from './meta';
import type { EntityType, GraphNode, GraphRelation, GraphStats, GraphView, RelationOrigin } from './types';

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

export function KnowledgeSection() {
    const [initial] = useState(readUrl);
    const [focusId, setFocusId] = useState<number | null>(initial.entityId);
    const [depth, setDepth] = useState(initial.depth);
    const [types, setTypes] = useState<EntityType[]>([]);
    const [fileId, setFileId] = useState('');
    const [files, setFiles] = useState<FileSummary[]>([]);

    const [data, setData] = useState<GraphView | null>(null);
    const [loadError, setLoadError] = useState('');
    const [positions, setPositions] = useState<Map<number, Point>>(new Map());
    const [fitKey, setFitKey] = useState(0);
    const [selection, setSelection] = useState<Selection>(initial.entityId ? { kind: 'node', id: initial.entityId } : null);
    const [reloadKey, setReloadKey] = useState(0);
    const [panelVersion, setPanelVersion] = useState(0);
    const [stats, setStats] = useState<GraphStats | null>(null);
    const [picking, setPicking] = useState(false);
    const [rebuildState, setRebuildState] = useState<'idle' | 'confirm' | 'sent'>('idle');

    const positionsRef = useRef(positions);
    const pinnedRef = useRef(new Set<number>());
    const pickCallback = useRef<((node: GraphNode) => void) | null>(null);
    // 보는 범위가 바뀌면 화면을 다시 맞추고, 편집 뒤 다시 불러올 때는 그대로 둔다
    const queryKey = `${focusId}|${depth}|${types.join(',')}|${fileId}`;
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
        graphApi.view(focusId !== null
            ? { entityId: focusId, depth, types, limit: FOCUS_LIMIT }
            : { types, fileId: fileId || null, limit: OVERVIEW_LIMIT },
        ).then((view) => {
            if (ignore) return;
            const queryChanged = lastQueryKey.current !== queryKey;
            lastQueryKey.current = queryKey;
            const ids = view.nodes.map((n) => n.id);
            const previous = queryChanged ? new Map<number, Point>() : positionsRef.current;
            if (queryChanged) pinnedRef.current = new Set();
            setPositions(layoutGraph(ids, view.edges, previous, pinnedRef.current));
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

    const focus = (id: number | null) => {
        setFocusId(id);
        if (id !== null) setSelection({ kind: 'node', id });
    };

    const selectedEdge: GraphRelation | null = useMemo(() => {
        if (selection?.kind !== 'edge' || !data) return null;
        const edge = data.edges.find((e) => e.id === selection.id);
        const source = edge && nodeById.get(edge.source);
        const target = edge && nodeById.get(edge.target);
        if (!edge || !source || !target) return null;
        return {
            id: edge.id, type: edge.type, origin: edge.origin, page: edge.page, file_id: edge.file_id, original_name: edge.original_name,
            source_id: source.id, source_type: source.type, source_name: source.name,
            target_id: target.id, target_type: target.type, target_name: target.name,
        };
    }, [selection, data, nodeById]);

    const toggleType = (type: EntityType) => {
        setTypes((list) => (list.includes(type) ? list.filter((t) => t !== type) : [...list, type].sort()));
    };

    const totalEntities = stats ? Object.values(stats.entities).reduce((a, b) => a + (b ?? 0), 0) : null;
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

            <div className="flex-1 min-h-0 flex flex-col md:flex-row">
                <main className="relative flex-1 min-w-0 min-h-[480px] bg-surface">
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
                        <div role="group" aria-label="개체 종류 거르기" className="pointer-events-auto flex flex-wrap gap-1">
                            {ENTITY_TYPES.map((t) => {
                                const active = types.includes(t);
                                return (
                                    <button
                                        key={t}
                                        type="button"
                                        aria-pressed={active}
                                        onClick={() => toggleType(t)}
                                        title={ENTITY_META[t].hint}
                                        className={`flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-semibold transition-colors ${active ? 'border-ink bg-ink text-white' : 'border-line bg-white text-ink/75 hover:bg-chip'}`}
                                    >
                                        <TypeDot type={t} className="w-2 h-2 ring-1 ring-white/70" />
                                        {ENTITY_META[t].label}
                                        {stats?.entities[t] !== undefined && <span className={active ? 'text-white/70' : 'text-muted'}>{stats.entities[t]}</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {picking && (
                        <div className="absolute left-1/2 top-16 z-20 -translate-x-1/2 rounded-full bg-ink px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-lg">
                            연결할 노드를 누르세요 · Esc로 취소
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
                            onMoveNode={(id, p) => {
                                pinnedRef.current.add(id);
                                setPositions((prev) => new Map(prev).set(id, p));
                            }}
                        />
                    )}

                    {/* 범례 */}
                    {data && !isEmpty && (
                        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-divide bg-white/90 px-2.5 py-1.5 text-[11px] text-muted">
                            {(Object.keys(ORIGIN_META) as RelationOrigin[]).map((origin) => (
                                <span key={origin} className="flex items-center gap-1.5">
                                    <svg width="22" height="6" aria-hidden>
                                        <line x1="0" y1="3" x2="22" y2="3" stroke={ORIGIN_META[origin].stroke} strokeWidth="2" strokeDasharray={ORIGIN_META[origin].dash} />
                                    </svg>
                                    {ORIGIN_META[origin].label}
                                </span>
                            ))}
                            <span>· 개체 {data.nodes.length} · 관계 {data.edges.length}{data.truncated && ' (일부만 표시)'}</span>
                        </div>
                    )}
                </main>

                <aside aria-label="선택한 개체" className="md:w-[360px] shrink-0 border-t md:border-t-0 md:border-l border-divide bg-white md:overflow-y-auto">
                    {selection?.kind === 'node' ? (
                        <EntityPanel
                            entityId={selection.id}
                            version={panelVersion}
                            onOpenEntity={(id) => setSelection({ kind: 'node', id })}
                            onFocus={focus}
                            onChanged={changed}
                            onMerged={(sourceId, targetId) => {
                                if (focusId === sourceId) setFocusId(targetId);
                                setSelection({ kind: 'node', id: targetId });
                                changed();
                            }}
                            requestPick={requestPick}
                        />
                    ) : selectedEdge ? (
                        <EdgePanel
                            relation={selectedEdge}
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
                                <li>사람이 고친 관계는 문서를 다시 추출해도 유지됩니다.</li>
                            </ul>
                            <div className="mt-4 grid grid-cols-2 gap-1.5">
                                {ENTITY_TYPES.map((t) => (
                                    <span key={t} className="flex items-center gap-1.5 text-[11.5px]">
                                        <TypeDot type={t} />
                                        <span className="text-ink/80">{ENTITY_META[t].label}</span>
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
