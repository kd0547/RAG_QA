import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

import { bounds, type Point } from './layout';
import { ENTITY_META, ORIGIN_META, RELATION_META, nodeRadius } from './meta';
import type { GraphEdge, GraphNode, RelationOrigin } from './types';

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
}) {
    const svgRef = useRef<SVGSVGElement>(null);
    const [view, setView] = useState<ViewBox>({ x: -300, y: -200, w: 600, h: 400 });
    const [hovered, setHovered] = useState<number | null>(null);
    const drag = useRef<
        | { kind: 'pan'; startX: number; startY: number; view: ViewBox; moved: boolean }
        | { kind: 'node'; id: number; startX: number; startY: number; moved: boolean }
        | null
    >(null);

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
        drag.current = { kind: 'node', id, startX: e.clientX, startY: e.clientY, moved: false };
    };
    const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
        const d = drag.current;
        if (!d) return;
        const distance = Math.hypot(e.clientX - d.startX, e.clientY - d.startY);
        if (!d.moved && distance < 4) return; // 클릭과 끌기를 구분한다
        d.moved = true;
        if (d.kind === 'node') {
            const p = toSvg(e.clientX, e.clientY);
            if (p) onMoveNode(d.id, p);
            return;
        }
        const rect = svgRef.current?.getBoundingClientRect();
        if (!rect) return;
        // preserveAspectRatio="meet"이라 가로·세로 중 큰 비율이 화면 1px의 크기다
        const scale = Math.max(d.view.w / rect.width, d.view.h / rect.height);
        setView({ ...d.view, x: d.view.x - (e.clientX - d.startX) * scale, y: d.view.y - (e.clientY - d.startY) * scale });
    };
    const onPointerUp = () => {
        const d = drag.current;
        drag.current = null;
        if (!d || d.moved) return;
        if (d.kind === 'pan') {
            if (!picking) onSelect(null);
        } else if (picking) {
            onPick(d.id);
        } else {
            onSelect({ kind: 'node', id: d.id });
        }
    };

    const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

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
    const edgeShapes = useMemo(() => {
        const groups = new Map<string, GraphEdge[]>();
        for (const e of edges) {
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
    }, [edges, positions, nodeById]);

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
                className={`h-full w-full touch-none select-none ${picking ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
                onPointerDown={onBackgroundDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => { drag.current = null; }}
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
                        return (
                            <g key={edge.id} opacity={dim ? 0.12 : 1}>
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
                                {RELATION_META[edge.type].label}
                            </text>
                        );
                    })}
                </g>

                <g>
                    {nodes.map((node) => {
                        const p = positions.get(node.id);
                        if (!p) return null;
                        const r = nodeRadius(node);
                        const meta = ENTITY_META[node.type];
                        const selected = node.id === selectedNodeId;
                        const dim = focus !== null && !focus.nodeIds.has(node.id);
                        const showLabel = showAllLabels || selected || hovered === node.id || node.degree >= 4
                            || node.type === 'concept' || (focus !== null && focus.nodeIds.has(node.id));
                        return (
                            <g
                                key={node.id}
                                transform={`translate(${p.x},${p.y})`}
                                opacity={dim ? 0.25 : 1}
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
                                <circle
                                    r={r}
                                    fill={node.type === 'concept' ? '#141C2B' : meta.color}
                                    fillOpacity={node.type === 'concept' ? 1 : 0.92}
                                    stroke="#fff"
                                    strokeWidth={2}
                                />
                                {node.type === 'concept' && <circle r={r - 5} fill="none" stroke="#fff" strokeWidth={1.4} />}
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
