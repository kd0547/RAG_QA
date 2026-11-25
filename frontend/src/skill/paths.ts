export type SkillTab = 'review' | 'active' | 'types';

/** SKILL 화면 경로. 고른 초안(doc)·SKILL(name)도 주소에 둔다 (새로 고침·뒤로 가기에도 그대로) */
export function skillPath(tab: SkillTab, params: { doc?: number | null; name?: string | null } = {}) {
    const q = new URLSearchParams();
    if (tab !== 'review') q.set('tab', tab);
    if (params.doc != null) q.set('doc', String(params.doc));
    if (params.name) q.set('name', params.name);
    const qs = q.toString();
    return `/skill${qs ? `?${qs}` : ''}`;
}
