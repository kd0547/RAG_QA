import { useEffect, useState } from 'react';

import { request } from '../lib/http';
import type { GraphMode, SpecAttribute } from './api';

/**
 * 속성 탭의 "그래프" 칸 (지시서 GR4-5): 사양 값 노드 / 대상 노드(관계·종류 선택) / 만들지 않음.
 * 저장하면 서버가 사양 DB를 그래프로 다시 투영한다. 엑셀 양식은 바뀌지 않는다.
 */
export interface GraphChoices { graph_mode: GraphMode; graph_relation_type: string | null; graph_entity_type: string | null }

interface SchemaLists { relation_types: { key: string; label: string; active: number | boolean }[]; entity_types: { key: string; label: string; active: number | boolean }[] }
let schemaCache: Promise<SchemaLists> | null = null;
function graphSchema(): Promise<SchemaLists> {
    schemaCache ??= request<SchemaLists>('/graph/schema').catch(() => ({ relation_types: [], entity_types: [] }));
    return schemaCache;
}

const selectCls = 'h-7 rounded-md border border-line bg-white px-1 text-[11.5px] disabled:opacity-50';

export function GraphModeCell({ attribute, busy, onChange }: { attribute: SpecAttribute; busy: boolean; onChange: (a: SpecAttribute, choice: GraphChoices) => void }) {
    const [lists, setLists] = useState<SchemaLists>({ relation_types: [], entity_types: [] });
    useEffect(() => { void graphSchema().then(setLists); }, []);
    const mode = attribute.graph_mode ?? 'value_node';
    const relation = attribute.graph_relation_type ?? 'has_component';
    const entity = attribute.graph_entity_type ?? 'component';
    const send = (patch: Partial<GraphChoices>) => {
        const next: GraphChoices = { graph_mode: mode, graph_relation_type: relation, graph_entity_type: entity, ...patch };
        onChange(attribute, next.graph_mode === 'entity' ? next : { ...next, graph_relation_type: null, graph_entity_type: null });
    };
    return (
        <td className="px-3 py-2">
            <select aria-label={`${attribute.name}: 그래프 방식`} value={mode} disabled={busy} className={selectCls}
                onChange={(e) => send({ graph_mode: e.target.value as GraphMode })}>
                <option value="value_node">사양 값 노드</option>
                <option value="entity">대상 노드</option>
                <option value="none">만들지 않음</option>
            </select>
            {mode === 'entity' && <div className="mt-1 flex flex-col gap-1">
                <select aria-label={`${attribute.name}: 관계 종류`} value={relation} disabled={busy} className={selectCls}
                    onChange={(e) => send({ graph_relation_type: e.target.value })}>
                    {lists.relation_types.filter((r) => r.active || r.key === relation).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                    {!lists.relation_types.some((r) => r.key === relation) && <option value={relation}>{relation}</option>}
                </select>
                <select aria-label={`${attribute.name}: 도착 노드 종류`} value={entity} disabled={busy} className={selectCls}
                    onChange={(e) => send({ graph_entity_type: e.target.value })}>
                    {lists.entity_types.filter((t) => t.active || t.key === entity).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                    {!lists.entity_types.some((t) => t.key === entity) && <option value={entity}>{entity}</option>}
                </select>
            </div>}
        </td>
    );
}
