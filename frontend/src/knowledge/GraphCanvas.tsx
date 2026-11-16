import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

import { bounds, type Point } from './layout';
import { ORIGIN_META, nodeRadius } from './meta';
import { entityMeta, relationLabel, useGraphSchema } from './schemaContext';
import type { GraphEdge, GraphNode, RelationOrigin } from './types';
import { groupRelations } from './relationGroups';

export type Selection = { kind: 'node'; id: number } | { kind: 'edge'; id: number } | null;

interface ViewBox {
    x: number;
    y: number;
    w: number;
    h: number;
}

const LABEL_ALL_LIMIT = 70; // 노드가 이보다 적으면 이름을 모두 보인다

export function GraphCanvas({
    nodes,
    edges,
    positions,
    selection,
    picking,
    fitKey,
    onSelect,
    onPick,
    onMoveNode,
    expandedIds = new Set<number>(),
    onToggleExpand,
    connectMode = false,
    onConnect,
    canMerge,
    onMergeDrop,
}: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    positions: Map<number, Point>;
    selection: Selection;
    /** 관계 추가에서 "그래프에서 고르기" 중이면 노드 클릭이 선택 대신 onPick으로 간다 */
    picking: boolean;
    /** 값이 바뀌면 전체가 보이게 화면을 맞춘다 */
    fitKey: number;
    onSelect: (selection: Selection) => void;
    onPick: (nodeId: number) => void;
    onMoveNode: (nodeId: number, point: Point) => void;
    /** 그래프에서 펼친 노드 (숨은 이웃을 보이는 중) */
    expandedIds?: Set<number>;
    /** 노드를 두 번 누르거나 +숫자를 누르면 숨은 이웃을 펼치고, 다시 하면 접는다 */
    onToggleExpand?: (nodeId: number) => void;
    /** 선 잇기: 노드를 누르면 선이 포인터를 따라오고, 다른 노드를 누르면 onConnect */
    connectMode?: boolean;
    /** 선 잇기로 두 노드를 골랐다. clientX·clientY는 두 번째 노드를 누른 화면 좌표 */
    onConnect?: (fromId: number, toId: number, clientX: number, clientY: number) => void;
    /** 끌고 있는 노드를 이 노드 위에 놓아 합칠 수 있는가 */
    canMerge?: (draggedId: number, targetId: number) => boolean;
    /** 노드를 합칠 수 있는 노드 위에 놓았다. origin은 끌기 전 위치 (취소하면 되돌린다) */
    onMergeDrop?: (draggedId: number, targetId: number, clientX: number, clientY: number, origin: Point | undefined) => void;
}) {
    const { schema } = useGraphSchema();
    const svgRef = useRef<SVGSVGElement>(null);
    const [view, setView] = useState<ViewBox>({ x: -300, y: -200, w: 600, h: 400 });
    const [hovered, setHovered] = useState<number | null>(null);
    // 선 잇기: 선이 시작된 노드와 지금 포인터 위치 (SVG 좌표)
    const [connectStart, setConnectStart] = useState<number | null>(null);
    const [pointer, setPointer] = useState<Point | null>(null);
    const connectFrom = connectMode ? connectStart : null;
    useEffect(() => {
        if (connectFrom === null) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setConnectStart(null); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [connectFrom]);
    const drag = useRef<
        | { kind: 'pan'; startX: number; startY: number; view: ViewBox; moved: boolean }
        | { kind: 'node'; id: number; startX: number; startY: number; moved: boolean; origin: Point | undefined }
        | null
    >(null);
    // 끌고 있는 노드를 놓으면 합칠 노드 (같은 종류 노드 위에 있을 때)
    const [dropTarget, setDropTarget] = useState<number | null>(null);
    const mergeEnabled = !!onMergeDrop && !!canMerge && !connectMode && !picking;

    const positionsRef = useRef(positions);
    useEffect(() => {
        positionsRef.current = positions;
    }, [positions]);

    // 새 데이터가 오면 전체가 보이게 맞춘다 (위 effect가 먼저 돌아 최신 위치를 본다)
    useEffect(() => {
        const b = bounds(positionsRef.current.values());
        setView({ x: b.minX, y: b.minY, w: b.width, h: b.height });
    }, [fitKey]);

    /** 화면 좌표 -> SVG 좌표 */
    const toSvg = useCallback((clientX: number, clientY: number): Point | null => {
        const svg = svgRef.current;
        const ctm = svg?.getScreenCTM();
        if (!svg || !ctm) return null;
        const p = svg.createSVGPoint();
        p.x = clientX;
        p.y = clientY;
        const r = p.matrixTransform(ctm.inverse());
        return { x: r.x, y: r.y };
    }, []);

    // 휠 확대·축소 (passive가 아니어야 페이지 스크롤을 막을 수 있다)
    useEffect(() => {
        const svg = svgRef.current;
        if (!svg) return;
        const onWheel = (e: WheelEvent) => {
            e.preventDefault();
            const at = toSvg(e.clientX, e.clientY);
            if (!at) return;
            const factor = Math.exp(Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY), 120) * 0.0018);
            setView((v) => {
                const w = Math.min(Math.max(v.w * factor, 80), 20000);
                const scale = w / v.w;
                const h = v.h * scale;
                return { x: at.x - (at.x - v.x) * scale, y: at.y - (at.y - v.y) * scale, w, h };
            });
        };
        svg.addEventListener('wheel', onWheel, { passive: false });
        return () => svg.removeEventListener('wheel', onWheel);
    }, [toSvg]);

    const zoomBy = (factor: number) => {
        setView((v) => {
            const cx = v.x + v.w / 2;
            const cy = v.y + v.h / 2;
            const w = Math.min(Math.max(v.w * factor, 80), 20000);
            const h = v.h * (w / v.w);
            return { x: cx - w / 2, y: cy - h / 2, w, h };
        });
    };
    const fit = () => {
        const b = bounds(positions.values());
        setView({ x: b.minX, y: b.minY, w: b.width, h: b.height });
    };

    const onBackgroundDown = (e: ReactPointerEvent<SVGSVGElement>) => {
        if (e.button !== 0) return;
        (e.currentTarget as Element).setPointerCapture(e.pointerId);
        drag.current = { kind: 'pan', startX: e.clientX, startY: e.clientY, view, moved: false };
    };
    const onNodeDown = (e: ReactPointerEvent<SVGGElement>, id: number) => {
        if (e.button !== 0) return;
        e.stopPropagation();
        svgRef.current?.setPointerCapture(e.pointerId);
        drag.current = { kind: 'node', id, startX: e.clientX, startY: e.clientY, moved: false, origin: positions.get(id) };
    };
    /** 포인터 아래(끌고 있는 노드 말고)에서 합칠 수 있는 가장 가까운 노드 */
    const findDropTarget = (draggedId: number, p: Point): number | null => {
        let best: number | null = null;
        let bestDistance = Infinity;
        for (const node of nodes) {
            if (node.id === draggedId) continue;
            const q = positions.get(node.id);
            if (!q) continue;
            const distance = Math.hypot(q.x - p.x, q.y - p.y);
            if (distance <= nodeRadius(node) + 8 && distance < bestDistance && canMerge?.(draggedId, node.id)) {
                best = node.id;
                bestDistance = distance;
            }
        }
        return best;
    };
    const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
        if (connectFrom !== null) {
            const p = toSvg(e.clientX, e.clientY);
            if (p) setPointer(p);
        }
        const d = drag.current;
        if (!d) return;
        const distance = Math.hypot(e.clientX - d.startX, e.clientY - d.startY);
        if (!d.moved && distance < 4) return; // 클릭과 끌기를 구분한다
        d.moved = true;
        if (d.kind === 'node') {
            const p = toSvg(e.clientX, e.clientY);
            if (p) {
                onMoveNode(d.id, p);
                if (mergeEnabled) setDropTarget(findDropTarget(d.id, p));
            }
            return;
        }
        const rect = svgRef.current?.getBoundingClientRect();
        if (!rect) return;
        // preserveAspectRatio="meet"이라 가로·세로 중 큰 비율이 화면 1px의 크기다
        const scale = Math.max(d.view.w / rect.width, d.view.h / rect.height);
        setView({ ...d.view, x: d.view.x - (e.clientX - d.startX) * scale, y: d.view.y - (e.clientY - d.startY) * scale });
    };
    const lastNodeClick = useRef<{ id: number; at: number } | null>(null);
    const onPointerUp = (e: ReactPointerEvent<SVGSVGElement>) => {
        const d = drag.current;
        drag.current = null;
        const target = dropTarget;
        setDropTarget(null);
        if (d?.kind === 'node' && d.moved && target !== null && mergeEnabled) {
            onMergeDrop?.(d.id, target, e.clientX, e.clientY, d.origin);
            return;
        }
        if (!d || d.moved) return;
        if (d.kind === 'pan') {
            if (connectFrom !== null) { setConnectStart(null); return; } // 빈 곳을 누르면 선 잇기 취소
            if (!picking) onSelect(null);
        } else if (picking) {
            onPick(d.id);
        } else if (connectMode && onConnect) {
            if (connectFrom === null) {
                // 첫 번째 노드: 선이 여기서 시작해 포인터를 따라온다
                setConnectStart(d.id);
                setPointer(toSvg(e.clientX, e.clientY));
                onSelect({ kind: 'node', id: d.id });
            } else if (connectFrom === d.id) {
                setConnectStart(null); // 같은 노드를 다시 누르면 취소
            } else {
                onConnect(connectFrom, d.id, e.clientX, e.clientY);
                setConnectStart(null);
            }
        } else {
            const now = e.timeStamp;
            const last = lastNodeClick.current;
            if (last && last.id === d.id && now - last.at < 350 && onToggleExpand) {
                lastNodeClick.current = null;
                onToggleExpand(d.id); // 두 번 누르면 펼치기·접기
                return;
            }
            lastNodeClick.current = { id: d.id, at: now };
            onSelect({ kind: 'node', id: d.id });
        }
    };

    const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
    // 노드마다 화면에 안 보이는 관계 수 (전체 관계 수 - 보이는 관계 수)
    const hiddenCount = useMemo(() => {
        const visible = new Map<number, number>();
        for (const e of edges) {
            visible.set(e.source, (visible.get(e.source) ?? 0) + 1);
            if (e.target !== e.source) visible.set(e.target, (visible.get(e.target) ?? 0) + 1);
        }
        return new Map(nodes.map((n) => [n.id, Math.max(0, n.degree - (visible.get(n.id) ?? 0))]));
    }, [nodes, edges]);

    // 선택한 노드와 바로 이어진 노드·엣지만 진하게 보인다
    const focus = useMemo(() => {
        if (!selection) return null;
        const nodeIds = new Set<number>();
        const edgeIds = new Set<number>();
        if (selection.kind === 'node') {
            nodeIds.add(selection.id);
            for (const e of edges) {
                if (e.source === selection.id || e.target === selection.id) {
                    edgeIds.add(e.id);
                    nodeIds.add(e.source);
                    nodeIds.add(e.target);
                }
            }
        } else {
            const edge = edges.find((e) => e.id === selection.id);
            if (edge) {
                edgeIds.add(edge.id);
                nodeIds.add(edge.source);
                nodeIds.add(edge.target);
            }
        }
        return { nodeIds, edgeIds };
    }, [selection, edges]);

    // 같은 두 노드 사이의 여러 관계는 휘어서 겹치지 않게 그린다
    // 같은 관계(출발·종류·도착)는 선 하나로 그리고 출처 수를 붙인다 (문서 관계는 근거 페이지마다 한 행이다)
    const sourceCount = useMemo(() => {
        const counts = new Map<number, number>();
        for (const list of groupRelations(edges)) counts.set(list[0].id, list.length);
        return counts;
    }, [edges]);
    const edgeShapes = useMemo(() => {
        const groups = new Map<string, GraphEdge[]>();
        for (const e of edges.filter((edge) => sourceCount.has(edge.id))) {
            const key = e.source < e.target ? `${e.source}-${e.target}` : `${e.target}-${e.source}`;
            const list = groups.get(key) ?? [];
            list.push(e);
            groups.set(key, list);
        }
        const shapes: { edge: GraphEdge; d: string; mid: Point }[] = [];
        for (const list of groups.values()) {
            list.forEach((e, i) => {
                const s = positions.get(e.source);
                const t = positions.get(e.target);
                const sn = nodeById.get(e.source);
                const tn = nodeById.get(e.target);
                if (!s || !t || !sn || !tn) return;
                const dx = t.x - s.x;
                const dy = t.y - s.y;
                const len = Math.hypot(dx, dy) || 1;
                const ux = dx / len;
                const uy = dy / len;
                // 휘는 정도: 가운데 기준으로 엣지마다 다르게. 방향이 반대인 엣지도 같은 쪽 기준으로 계산한다
                const sign = e.source < e.target ? 1 : -1;
                const bend = (i - (list.length - 1) / 2) * 26 * sign;
                const cx = (s.x + t.x) / 2 - uy * bend;
                const cy = (s.y + t.y) / 2 + ux * bend;
                const tr = nodeRadius(tn) + 4;
                const sr = nodeRadius(sn) + 1;
                // 끝점을 노드 테두리까지 줄인다 (제어점 방향 기준)
                const ex = t.x - ((t.x - cx) / (Math.hypot(t.x - cx, t.y - cy) || 1)) * tr;
                const ey = t.y - ((t.y - cy) / (Math.hypot(t.x - cx, t.y - cy) || 1)) * tr;
                const bx = s.x + ((cx - s.x) / (Math.hypot(cx - s.x, cy - s.y) || 1)) * sr;
                const by = s.y + ((cy - s.y) / (Math.hypot(cx - s.x, cy - s.y) || 1)) * sr;
                shapes.push({
                    edge: e,
                    d: `M${bx},${by} Q${cx},${cy} ${ex},${ey}`,
                    mid: { x: 0.25 * bx + 0.5 * cx + 0.25 * ex, y: 0.25 * by + 0.5 * cy + 0.25 * ey },
                });
            });
        }
        return shapes;
    }, [edges, positions, nodeById, sourceCount]);

    const showAllLabels = nodes.length <= LABEL_ALL_LIMIT;
    const selectedNodeId = selection?.kind === 'node' ? selection.id : null;
    const selectedEdgeId = selection?.kind === 'edge' ? selection.id : null;

    return (
        <div className="relative h-full w-full">
            <svg
                ref={svgRef}
                role="img"
                aria-label={`지식 그래프: 개체 ${nodes.length}개, 관계 ${edges.length}개`}
                viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
                preserveAspectRatio="xMidYMid meet"
                className={`h-full w-full touch-none select-none ${picking || connectMode ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
                onPointerDown={onBackgroundDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => { drag.current = null; setDropTarget(null); }}
            >
                <defs>
                    {(Object.keys(ORIGIN_META) as RelationOrigin[]).map((origin) => (
                        <marker key={origin} id={`arrow-${origin}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                            <path d="M0,0 L10,5 L0,10 z" fill={ORIGIN_META[origin].stroke} />
                        </marker>
                    ))}
                    <marker id="arrow-selected" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                        <path d="M0,0 L10,5 L0,10 z" fill="#141C2B" />
                    </marker>
                </defs>

                <g>
                    {edgeShapes.map(({ edge, d }) => {
                        const meta = ORIGIN_META[edge.origin];
                        const selected = edge.id === selectedEdgeId;
                        const dim = focus !== null && !focus.edgeIds.has(edge.id);
                        // 사양 값 관계는 옅게 (고른 노드의 관계면 진하게)
                        const faint = edge.type === 'has_spec' && !selected && !(focus !== null && focus.edgeIds.has(edge.id));
                        return (
                            <g key={edge.id} opacity={dim ? (faint ? 0.06 : 0.12) : faint ? 0.3 : 1}>
                                {/* 클릭하기 쉽게 투명한 굵은 선을 깐다 */}
                                <path
                                    d={d}
                                    fill="none"
                                    stroke="transparent"
                                    strokeWidth={12}
                                    className={picking ? '' : 'cursor-pointer'}
                                    onPointerDown={(e) => e.stopPropagation()}
                                    onPointerUp={(e) => {
                                        e.stopPropagation();
                                        drag.current = null;
                                        if (!picking) onSelect({ kind: 'edge', id: edge.id });
                                    }}
                                />
                                <path
                                    d={d}
                                    fill="none"
                                    stroke={selected ? '#141C2B' : meta.stroke}
                                    strokeWidth={selected ? 2.4 : edge.origin === 'manual' ? 1.8 : 1.3}
                                    strokeDasharray={meta.dash}
                                    markerEnd={`url(#arrow-${selected ? 'selected' : edge.origin})`}
                                    pointerEvents="none"
                                />
                            </g>
                        );
                    })}
                </g>

                <g>
                    {edgeShapes.map(({ edge, mid }) => {
                        const show = edge.id === selectedEdgeId || (focus !== null && focus.edgeIds.has(edge.id))
                            || (hovered !== null && (edge.source === hovered || edge.target === hovered));
                        if (!show) return null;
                        return (
                            <text
                                key={edge.id}
                                x={mid.x}
                                y={mid.y}
                                textAnchor="middle"
                                dominantBaseline="central"
                                className="text-[10px] font-semibold"
                                fill={edge.id === selectedEdgeId ? '#141C2B' : '#5B6678'}
                                stroke="#fff"
                                strokeWidth={3.5}
                                paintOrder="stroke"
                                pointerEvents="none"
                            >
                                {relationLabel(schema, edge.type)}{(sourceCount.get(edge.id) ?? 1) > 1 ? ` · 출처 ${sourceCount.get(edge.id)}` : ''}
                            </text>
                        );
                    })}
                </g>

                {connectFrom !== null && pointer && positions.get(connectFrom) && (
                    <line x1={positions.get(connectFrom)!.x} y1={positions.get(connectFrom)!.y} x2={pointer.x} y2={pointer.y}
                        stroke="#00A4E4" strokeWidth={2} strokeDasharray="6 4" pointerEvents="none" />
                )}
                <g>
                    {nodes.map((node) => {
                        const p = positions.get(node.id);
                        if (!p) return null;
                        const r = nodeRadius(node);
                        const meta = entityMeta(schema, node.type);
                        const selected = node.id === selectedNodeId;
                        const dim = focus !== null && !focus.nodeIds.has(node.id);
                        // 노드가 많으면 제품군·제품 이름만 늘 보이고, 나머지는 고르거나 마우스를 올리면 보인다
                        const showLabel = showAllLabels || selected || hovered === node.id
                            || node.type === 'product' || node.type === 'product_line'
                            || (node.type !== 'spec_value' && node.degree >= 4 && nodes.length <= 60)
                            || (focus !== null && focus.nodeIds.has(node.id) && (focus.nodeIds.size <= 40 || node.type !== 'spec_value'));
                        return (
                            <g
                                key={node.id}
                                transform={`translate(${p.x},${p.y})`}
                                opacity={dim && dropTarget !== node.id ? 0.25 : 1}
                                role="button"
                                tabIndex={0}
                                aria-label={`${meta.label} ${node.name}`}
                                aria-pressed={selected}
                                className="cursor-pointer outline-none"
                                onPointerDown={(e) => onNodeDown(e, node.id)}
                                onPointerEnter={() => setHovered(node.id)}
                                onPointerLeave={() => setHovered((h) => (h === node.id ? null : h))}
                                onKeyDown={(e) => {
                                    if (e.key !== 'Enter' && e.key !== ' ') return;
                                    e.preventDefault();
                                    if (picking) onPick(node.id);
                                    else onSelect({ kind: 'node', id: node.id });
                                }}
                            >
                                {selected && <circle r={r + 5} fill="none" stroke={meta.color} strokeOpacity={0.35} strokeWidth={4} />}
                                {connectFrom !== null && connectFrom !== node.id && hovered === node.id && (
                                    <circle r={r + 7} fill="none" stroke="#00A4E4" strokeWidth={3} strokeDasharray="4 3" />
                                )}
                                {dropTarget === node.id && (
                                    <>
                                        <circle r={r + 9} fill="#F59E0B" fillOpacity={0.15} stroke="#F59E0B" strokeWidth={3} />
                                        <text y={-r - 15} textAnchor="middle" className="text-[11px] font-bold" fill="#B45309"
                                            stroke="#fff" strokeWidth={3.5} paintOrder="stroke" pointerEvents="none">
                                            놓으면 합치기
                                        </text>
                                    </>
                                )}
                                <circle
                                    r={r}
                                    fill={meta.color}
                                    fillOpacity={node.type === 'spec_value' ? 0.6 : 0.92}
                                    stroke="#fff"
                                    strokeWidth={2}
                                />
                                {onToggleExpand && (expandedIds.has(node.id)
                                    || ((selected || hovered === node.id) && (hiddenCount.get(node.id) ?? 0) > 0)) && (
                                    <g
                                        transform={`translate(${r * 0.75},${-r * 0.75})`}
                                        role="button"
                                        aria-label={expandedIds.has(node.id) ? `${node.name} 접기` : `${node.name}의 숨은 관계 ${hiddenCount.get(node.id)}개 펼치기`}
                                        className="cursor-pointer"
                                        onPointerDown={(e) => { e.stopPropagation(); }}
                                        onClick={(e) => { e.stopPropagation(); onToggleExpand(node.id); }}
                                    >
                                        <title>{expandedIds.has(node.id) ? '펼친 이웃 접기' : `숨은 관계 ${hiddenCount.get(node.id)}개 펼치기`}</title>
                                        <rect x={-2} y={-7} rx={7} height={14}
                                            width={expandedIds.has(node.id) ? 16 : 10 + String(hiddenCount.get(node.id)).length * 6.5}
                                            fill={expandedIds.has(node.id) ? '#141C2B' : '#fff'} stroke="#141C2B" strokeOpacity={0.35} />
                                        <text x={expandedIds.has(node.id) ? 6 : 3} y={3.5} className="text-[9.5px] font-bold" fill={expandedIds.has(node.id) ? '#fff' : '#141C2B'} pointerEvents="none">
                                            {expandedIds.has(node.id) ? '−' : `+${hiddenCount.get(node.id)}`}
                                        </text>
                                    </g>
                                )}
                                {showLabel && (
                                    <text
                                        y={r + 12}
                                        textAnchor="middle"
                                        className={`text-[11px] ${selected ? 'font-bold' : 'font-semibold'}`}
                                        fill="#141C2B"
                                        stroke="#fff"
                                        strokeWidth={3.5}
                                        paintOrder="stroke"
                                        pointerEvents="none"
                                    >
                                        {node.name.length > 26 ? `${node.name.slice(0, 25)}…` : node.name}
                                    </text>
                                )}
                            </g>
                        );
                    })}
                </g>
            </svg>

            <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-lg border border-line bg-white shadow-[0_1px_3px_rgba(20,28,43,0.08)]">
                <button type="button" onClick={() => zoomBy(0.8)} aria-label="확대" className="h-8 w-8 text-[15px] font-semibold text-ink/70 hover:bg-chip">+</button>
                <button type="button" onClick={() => zoomBy(1.25)} aria-label="축소" className="h-8 w-8 border-t border-divide text-[15px] font-semibold text-ink/70 hover:bg-chip">−</button>
                <button type="button" onClick={fit} aria-label="전체가 보이게 맞추기" title="전체가 보이게 맞추기" className="h-8 w-8 border-t border-divide text-[11px] font-bold text-ink/70 hover:bg-chip">⤢</button>
            </div>
        </div>
    );
}
