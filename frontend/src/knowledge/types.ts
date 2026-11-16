/** 문서 그래프 API 타입 (백엔드: app/routers/graph.py, repository/graph_repository.py) */

/** graph_entity_type의 key. 종류 목록은 GET /graph/schema가 준다 (지시서 GR2) */
export type EntityType = string;

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

/** 사양 DB 값 하나 (agent.spec_service.effective_specs) */
export interface SpecValueItem {
    spec_value_id: number; attribute_key: string; attribute_name: string; category: string; data_type: string; unit: string;
    value_text: string; value_num: number | null; is_option: number | boolean; inherited_from: string | null; via_component: string | null;
}
export interface HierarchyItem { id: number; name: string; type: EntityType }

export interface GraphEntityDetail {
    /** 모델 계층 (variant_of): 상위 경로(루트부터)와 바로 아래 하위 모델 */
    hierarchy?: { ancestors: HierarchyItem[]; children: HierarchyItem[] };
    /** 사양 DB 제품·부품 노드의 그때 값. 읽지 못하면 null */
    spec?: { values: SpecValueItem[] } | null;
    /** 사양 값 노드의 속성 정보 */
    spec_attribute?: { key: string; name: string; unit: string; data_type: string; category: string; value_key: string | null; value_num: number | null } | null;
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
