/**
 * 관계를 사람이 읽는 말로 바꾼다 (화면 전용, 백엔드 변경 없음).
 * - relationPhrase: 관계 하나를 문장으로 ("A600은 KC 안전확인 인증을 받았다")
 * - groupTitle: 개체 패널의 묶음 제목. 보고 있는 개체 입장에서 쓴다 (나가는 관계 "번호" / 들어오는 관계 "이 번호를 쓰는 제품")
 * - allowedChoices: 두 개체 사이에 규칙(허용 출발·도착 종류, GET /graph/schema)대로 쓸 수 있는 관계와 방향.
 *   방향은 종류로 정한다. 사용자가 어느 노드에서 선을 시작했는지와 무관하다.
 * 사용자가 만든 관계 종류는 문장 틀이 없어 "출발 → 관계 이름 → 도착", 묶음 제목은 "관계 이름" / "관계 이름 (받는 쪽)"이다.
 */
import type { GraphSchema, RelationDefinition } from './schemaContext';
import type { EntityType } from './types';

/** 받침 유무로 조사를 고른다. 한글로 끝나지 않으면 "은(는)"처럼 둘 다 쓴다 */
function particle(word: string, withFinal: string, withoutFinal: string): string {
    const code = word.trim().slice(-1).charCodeAt(0) - 0xac00;
    if (Number.isNaN(code) || code < 0 || code > 11171) return `${withFinal}(${withoutFinal})`;
    return code % 28 === 0 ? withoutFinal : withFinal;
}
const topic = (w: string) => `${w}${particle(w, '은', '는')}`;
const subject = (w: string) => `${w}${particle(w, '이', '가')}`;

const PHRASES: Record<string, (source: string, target: string) => string> = {
    has_certification: (s, t) => `${topic(s)} ${t} 인증을 받았다`,
    has_number: (s, t) => `${s}의 번호는 ${t}`,
    issued_by: (s, t) => `${topic(s)} ${subject(t)} 발급했다`,
    made_by: (s, t) => `${topic(s)} ${subject(t)} 만들었다`,
    has_component: (s, t) => `${s}에 ${t} 부품이 들어간다`,
    complies_with: (s, t) => `${topic(s)} ${t} 규격을 따른다`,
    variant_of: (s, t) => `${topic(s)} ${t}의 하위 모델이다`,
    has_spec: (s, t) => `${s}의 사양: ${t}`,
};

function relationName(schema: GraphSchema, type: string): string {
    return schema.relation_types.find((r) => r.key === type)?.label ?? type;
}

/** 그래프 선 위 글자: 화살표 방향대로 "출발 ○○ 도착"으로 읽히는 짧은 말 */
const EDGE_LABELS: Record<string, string> = {
    has_component: '부품으로 씀',
    variant_of: '의 하위 모델',
    has_certification: '인증 받음',
    complies_with: '규격 따름',
    made_by: '만든 회사',
    issued_by: '발급 기관',
    has_number: '번호',
    has_spec: '사양',
};

/** 선 위 글자. 사용자가 만든 관계 종류는 등록된 이름 그대로 */
export function edgeLabel(schema: GraphSchema, type: string): string {
    return EDGE_LABELS[type] ?? relationName(schema, type);
}

export function relationPhrase(schema: GraphSchema, type: string, source: string, target: string): string {
    const phrase = PHRASES[type];
    return phrase ? phrase(source, target) : `${source} → ${relationName(schema, type)} → ${target}`;
}

const TITLES: Record<string, [outgoing: string, incoming: (noun: string) => string]> = {
    has_number: ['번호', (n) => `이 번호를 쓰는 ${n}`],
    has_certification: ['받은 인증', (n) => `이 인증을 받은 ${n}`],
    made_by: ['만든 회사', () => '이 회사가 만든 것'],
    issued_by: ['발급한 기관', () => '이 기관이 발급한 것'],
    has_component: ['들어간 부품', (n) => `이 부품을 쓰는 ${n}`],
    complies_with: ['따르는 규격', () => '이 규격을 따르는 것'],
    variant_of: ['상위 모델', () => '하위 모델'],
    has_spec: ['사양 값', (n) => `이 값을 가진 ${n}`],
};

/**
 * 묶음 제목. outgoing이면 보고 있는 개체가 출발이다. otherTypes는 상대 개체들의 종류
 * (모두 제품·제품군이면 "제품", 아니면 "대상"이라고 쓴다).
 */
export function groupTitle(schema: GraphSchema, type: string, outgoing: boolean, otherTypes: EntityType[]): string {
    const noun = otherTypes.every((t) => t === 'product' || t === 'product_line') ? '제품' : '대상';
    const title = TITLES[type];
    if (title) return outgoing ? title[0] : title[1](noun);
    return outgoing ? relationName(schema, type) : `${relationName(schema, type)} (받는 쪽)`;
}

export interface RelationChoice {
    definition: RelationDefinition;
    /** true면 a → b, false면 b → a */
    forward: boolean;
}

/** a·b 사이에 규칙대로 쓸 수 있는 관계와 방향 (사용 중인 관계 종류만, 한 종류는 한 방향만) */
export function allowedChoices(schema: GraphSchema, aType: EntityType, bType: EntityType): RelationChoice[] {
    const choices: RelationChoice[] = [];
    for (const definition of schema.relation_types) {
        if (!definition.active) continue;
        if (definition.source_entity_types.includes(aType) && definition.target_entity_types.includes(bType)) {
            choices.push({ definition, forward: true });
        } else if (definition.source_entity_types.includes(bType) && definition.target_entity_types.includes(aType)) {
            choices.push({ definition, forward: false });
        }
    }
    return choices;
}
