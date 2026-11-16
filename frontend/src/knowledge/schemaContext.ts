import { createContext, useContext } from 'react';
import type { EntityType } from './types';
export interface RelationDefinition {
    key: string; label: string; description: string; source_entity_types: EntityType[];
    target_entity_types: EntityType[]; allow_self: boolean; active: boolean; builtin: boolean; revision: number;
}
export interface PropertyDefinition {
    property_id: number; key: string; label: string; value_type: 'text' | 'number' | 'boolean' | 'date' | 'enum';
    unit: string | null; allowed_values: string[]; allowed_entity_types: EntityType[];
    multiple: boolean; active: boolean; revision: number;
}
export interface GraphSchema {
    editing_enabled: boolean; schema_revision: number;
    relation_types: RelationDefinition[]; property_definitions: PropertyDefinition[];
}
export const empty: GraphSchema = { editing_enabled: false, schema_revision: 0, relation_types: [], property_definitions: [] };
export const Context = createContext({ schema: empty, refresh: () => {}, error: '' });
export function useGraphSchema() { return useContext(Context); }
export function relationLabel(schema: GraphSchema, key: string) {
    return schema.relation_types.find((r) => r.key === key)?.label ?? key;
}
