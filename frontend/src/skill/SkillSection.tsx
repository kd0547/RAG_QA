import { useCallback, useSyncExternalStore } from 'react';
import { AppHeader } from '../components/AppHeader';
import { linkProps, navigate, subscribeRoute } from '../lib/router';
import { ActiveTab } from './ActiveTab';
import { ReviewTab } from './ReviewTab';
import { TypesTab } from './TypesTab';
import { skillPath, type SkillTab } from './paths';

const TABS: { key: SkillTab; label: string }[] = [
    { key: 'review', label: '검토 대기' },
    { key: 'active', label: '사용 중 절차' },
    { key: 'types', label: '문의 유형' },
];

const getSearch = () => window.location.search;

/**
 * 업무 절차 (지시서 I6).
 * - 검토 대기: 문의 사례로 만든 절차 초안을 R&D가 고치고 승인·반려한다
 * - 사용 중 절차: 저장소 절차(기본)와 승인된 생성 절차. 생성 절차는 고치기(새 버전)·사용 중지
 * - 문의 유형: 분석이 나눈 문의 유형별 건수와 맡는 절차. 초안 만들기·절차 불필요·합치기
 */
export function SkillSection() {
    const search = useSyncExternalStore(subscribeRoute, getSearch);
    const params = new URLSearchParams(search);
    const tabParam = params.get('tab');
    const tab: SkillTab = tabParam === 'active' || tabParam === 'types' ? tabParam : 'review';
    const docParam = Number(params.get('doc'));
    const doc = Number.isInteger(docParam) && docParam > 0 ? docParam : null;
    const name = params.get('name');
    const selectDraft = useCallback(
        (id: number | null, replace = false) => navigate(skillPath('review', { doc: id }), { replace }),
        [],
    );
    const selectSkill = useCallback(
        (n: string | null, replace = false) => navigate(skillPath('active', { name: n }), { replace }),
        [],
    );

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader current="skill">
                <nav className="flex items-center gap-1 min-w-0 overflow-x-auto [scrollbar-width:none]">
                    {TABS.map((t) => {
                        const active = t.key === tab;
                        return (
                            <a
                                key={t.key}
                                {...linkProps(skillPath(t.key))}
                                aria-current={active ? 'page' : undefined}
                                className={`h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-semibold whitespace-nowrap transition-colors ${
                                    active ? 'bg-chip text-ink' : 'text-muted hover:text-ink'
                                }`}
                            >
                                {t.label}
                            </a>
                        );
                    })}
                </nav>
            </AppHeader>

            <div className="flex-1 min-h-0 flex flex-col">
                {tab === 'review' && <ReviewTab docId={doc} onSelect={selectDraft} />}
                {tab === 'active' && (
                    <ActiveTab name={name} onSelect={selectSkill} onOpenDraft={(id) => selectDraft(id)} />
                )}
                {tab === 'types' && <TypesTab onOpenDraft={(id) => selectDraft(id)} />}
            </div>
        </div>
    );
}
