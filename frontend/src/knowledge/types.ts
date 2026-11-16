/** 문서 그래프 API 타입 (백엔드: app/routers/graph.py, repository/graph_repository.py) */

export type EntityType =
    | 'product'
    | 'component'
    | 'certification'
    | 'cert_number'
    | 'organization'
    | 'standard';

export type RelationType = string;

/** extract: 문서에서 뽑음 · seed: 옛 기본 연결(지금은 만들지 않음) · manual: 사람이 넣음 (다시 뽑아도 유지) · spec: 사양 DB에서 심음 */
export type RelationOrigin = 'extract' | 'seed' | 'manual' | 'spec';

export interface GraphNode {
    revision: number;
    id: number;
    type: EntityType;
    name: string;
    mention_count: number;
    degree: number;
}

export interface GraphEdge {
    revision: number;
    id: number;
    source: number;
    target: number;
    type: RelationType;
    origin: RelationOrigin;
    file_id: string | null;
    page: number | null;
    original_name: string | null;
}

export interface GraphView {
    nodes: GraphNode[];
    edges: GraphEdge[];
    /** limit에 걸려 일부만 보여줌 */
    truncated: boolean;
}

export interface GraphRelation {
    revision: number;
    sources?: FactSource[];
    id: number;
    type: RelationType;
    origin: RelationOrigin;
    page: number | null;
    file_id: string | null;
    original_name: string | null;
    source_id: number;
    source_type: EntityType;
    source_name: string;
    target_id: number;
    target_type: EntityType;
    target_name: string;
}

export interface GraphEntityDetail {
    revision: number;
    ref_type: string | null;
    ref_id: string | null;
    creation_origin: string;
    properties: PropertyValue[];
    id: number;
    type: EntityType;
    name: string;
    aliases: string[];
    relations: GraphRelation[];
    mentions: { file_id: string; page: number; original_name: string }[];
}

export interface GraphEntitySummary {
    revision: number;
    id: number;
    type: EntityType;
    name: string;
    mention_count: number;
    relation_count: number;
}

export interface GraphStats {
    entities: Partial<Record<EntityType, number>>;
    relations: number;
    relations_by_origin: Partial<Record<RelationOrigin, number>>;
    blocked_relations: number;
    indexed_files: number;
}

export interface RelationCreateInput {
    source?: { reason: string; file_id?: string | null; page?: number | null };
    reverse?: boolean;
    source_id: number;
    type: RelationType;
    target_id?: number;
    new_target?: { type: EntityType; name: string };
    file_id?: string | null;
    page?: number | null;
}

export interface FactSource {
    source_id: number; source_name: string | null; page: number | null; file_deleted: boolean;
    reason: string; verification: string; revision: string | null;
}
export interface PropertyValue {
    value_id: number; property_id: number; label: string; value_type: string; unit: string | null;
    value: string | number | boolean | null; revision: number; confirmation: string; sources: FactSource[];
}
