/** 문서 그래프 API 타입 (백엔드: app/routers/graph.py, repository/graph_repository.py) */

export type EntityType =
    | 'product'
    | 'component'
    | 'certification'
    | 'cert_number'
    | 'organization'
    | 'standard'
    | 'concept';

export type RelationType =
    | 'has_component'
    | 'has_certification'
    | 'has_number'
    | 'issued_by'
    | 'complies_with'
    | 'part_of';

/** extract: 문서에서 뽑음 · seed: aliases.yaml · manual: 사람이 넣음 (다시 뽑아도 유지) */
export type RelationOrigin = 'extract' | 'seed' | 'manual';

export interface GraphNode {
    id: number;
    type: EntityType;
    name: string;
    mention_count: number;
    degree: number;
}

export interface GraphEdge {
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
    id: number;
    type: EntityType;
    name: string;
    aliases: string[];
    relations: GraphRelation[];
    mentions: { file_id: string; page: number; original_name: string }[];
}

export interface GraphEntitySummary {
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
    source_id: number;
    type: RelationType;
    target_id?: number;
    new_target?: { type: EntityType; name: string };
    file_id?: string | null;
    page?: number | null;
}
