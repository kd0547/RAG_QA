/** 사양 관리 화면 공용 클래스 문자열과 유틸. 컴포넌트는 ui.tsx 에 있다. */
import { ApiError } from '../lib/http';

export const inputCls =
    'block h-9 w-full rounded-lg border border-line bg-white px-3 text-[13px] text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10 disabled:opacity-50';
export const selectCls = inputCls;
export const smallInputCls =
    'block h-8 w-full rounded-md border border-line bg-white px-2 text-[12px] text-ink placeholder:text-muted focus:border-brand focus:outline-none disabled:opacity-50';
export const btnPrimary =
    'inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand px-4 text-[12.5px] font-bold text-white enabled:hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40 transition-colors';
export const btnGhost =
    'inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-3 text-[12.5px] font-semibold text-ink hover:bg-chip disabled:cursor-not-allowed disabled:opacity-40 transition-colors';
export const btnDanger =
    'inline-flex h-9 items-center gap-1.5 rounded-lg border border-danger/30 bg-white px-3 text-[12.5px] font-semibold text-danger hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-40 transition-colors';
export const btnTiny =
    'inline-flex h-7 items-center rounded-md px-2 text-[11.5px] font-semibold text-muted hover:text-ink hover:bg-chip disabled:opacity-40 transition-colors';

export function errorMessage(e: unknown, fallback: string): string {
    if (e instanceof ApiError) return e.status === 0 ? '서버에 연결하지 못했습니다.' : e.message;
    return e instanceof Error && e.message ? e.message : fallback;
}

export function formatDate(value: string | null | undefined): string {
    if (!value) return '';
    // SQLite의 current_timestamp 기본값("2026-11-05 04:19:00")은 UTC라 Z를 붙여 읽는다. 'T'가 있는 값은 서버가 로컬 시각으로 쓴 것이다
    const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/**
 * 부품 종류별로 보여줄 속성 분류. 백엔드 속성 사전에는 대상 구분이 없어서 화면에서 분류로 추린다.
 * '기타' 분류(보증 기간, TG 승인 여부 등)는 모든 대상에 보인다. 제품(product)과 '기타' 부품은 전부 보인다.
 */
const KIND_CATEGORIES: Record<string, string[]> = {
    cpu: ['cpu'],
    gpu: ['graphics'],
    memory: ['memory'],
    ssd: ['storage'],
    wifi: ['network'],
    display: ['display'],
    battery: ['power'],
    adapter: ['power'],
};

/** scope가 'product'거나 대응 분류가 없으면 전부, 아니면 그 분류 + 기타만 */
export function attributesFor<T extends { category: string }>(attributes: T[], scope: string | null): T[] {
    if (!scope) return attributes;
    const categories = KIND_CATEGORIES[scope];
    if (!categories) return attributes;
    return attributes.filter((a) => categories.includes(a.category) || a.category === 'other');
}

export function labelOf(map: Record<string, string> | undefined, key: string): string {
    return map?.[key] ?? key;
}

/** 이름 비교용: 대소문자·공백·기호를 무시한다 ("TG승인 여부" = "TG 승인 여부") */
export function normalizeName(value: string): string {
    return value.toLowerCase().replace(/[\s_\-·.()/]+/g, '');
}

/** 이름이 같은(정규화 기준) 속성. 새 속성을 만들기 전에 중복을 막는 데 쓴다 */
export function sameNameAttribute<T extends { name: string; key: string }>(attributes: T[], name: string): T | undefined {
    const n = normalizeName(name);
    if (!n) return undefined;
    return attributes.find((a) => normalizeName(a.name) === n || normalizeName(a.key) === n);
}

const ATTRIBUTE_KEY_RE = /^[a-z][a-z0-9_]{1,49}$/;

/** 속성 키를 이름에서 자동으로 만든다. 영문 이름이면 그대로 바꾸고, 한글이면 attr_시각 형태로 만든다 */
export function autoAttributeKey(name: string, existingKeys: Iterable<string>): string {
    const taken = new Set(existingKeys);
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
    let base = ATTRIBUTE_KEY_RE.test(slug) ? slug : `attr_${Date.now().toString(36)}`;
    if (!ATTRIBUTE_KEY_RE.test(base)) base = `attr_${Date.now().toString(36)}`;
    let key = base;
    for (let i = 2; taken.has(key); i++) key = `${base}_${i}`;
    return key;
}

/** 분류의 맨 뒤 정렬 순서 (새 속성을 분류 끝에 둔다) */
export function nextSortOrder(attributes: { category: string; sort_order: number }[], category: string): number {
    const orders = attributes.filter((a) => a.category === category).map((a) => a.sort_order);
    return orders.length ? Math.max(...orders) + 1 : 0;
}

/** 부품 종류에 맞는 첫 분류 (새 속성의 기본 분류). 제품이면 '기타' */
export function defaultCategoryFor(scope: string | null): string {
    return (scope && KIND_CATEGORIES[scope]?.[0]) || 'other';
}
