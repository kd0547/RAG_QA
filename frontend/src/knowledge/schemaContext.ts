import { createContext, useContext } from 'react';
import type { EntityType } from './types';
export interface RelationDefinition {
    key: string; label: string; description: string; source_entity_types: EntityType[];
    target_entity_types: EntityType[]; allow_self: boolean; active: boolean; builtin: boolean; revision: number;
    extract: number | boolean;
}
/** 개체 종류 (graph_entity_type). 0/1 값은 SQLite 정수로 온다 */
export interface EntityTypeDefinition {
    key: string; label: string; description: string; color: string; extract: number; requires_identifier: number;
    builtin: number; active: number; sort_order: number; revision: number; used_by_projection: boolean; entity_count: number;
}
export interface PropertyDefinition {
    property_id: number; key: string; label: string; value_type: 'text' | 'number' | 'boolean' | 'date' | 'enum';
    unit: string | null; allowed_values: string[]; allowed_entity_types: EntityType[];
    multiple: boolean; active: boolean; revision: number;
}
export interface GraphSchema {
    editing_enabled: boolean; schema_revision: number; entity_types: EntityTypeDefinition[];
    relation_types: RelationDefinition[]; property_definitions: PropertyDefinition[];
}
export const empty: GraphSchema = { editing_enabled: false, schema_revision: 0, entity_types: [], relation_types: [], property_definitions: [] };
const FALLBACK_COLOR = '#94A3B8';
/** 종류의 화면 이름·색·설명. 목록에 없는 종류(지운 종류의 병합 흔적 등)는 key를 그대로 쓴다 */
export function entityMeta(schema: GraphSchema, key: EntityType): { label: string; color: string; hint: string } {
    const type = schema.entity_types.find((t) => t.key === key);
    return { label: type?.label ?? key, color: type?.color ?? FALLBACK_COLOR, hint: type?.description ?? '' };
}
/** 선택 목록에 보일 종류 key. 기본은 사용 중인 것만, 사용 중지된 종류도 개체가 있으면 넣는다 */
export function typeKeys(schema: GraphSchema, includeInactiveWithEntities = false): EntityType[] {
    return schema.entity_types.filter((t) => t.active || (includeInactiveWithEntities && t.entity_count > 0)).map((t) => t.key);
}
export const Context = createContext({ schema: empty, refresh: () => {}, error: '' });
export function useGraphSchema() { return useContext(Context); }
export function relationLabel(schema: GraphSchema, key: string) {
    return schema.relation_types.find((r) => r.key === key)?.label ?? key;
}
