import { useCallback, useEffect, useRef, useState } from 'react';
import { AppHeader } from '../components/AppHeader';
import { linkProps } from '../lib/router';
import { mailApi } from './api';
import { MAIL_PATHS, REVIEW_STATUSES } from './format';
import { MOCK_STATS } from './mockData';
import type { MailStats } from './types';
import { MockBadge } from './ui';
import { useMailList } from './useMailList';
import { MailDashboardPage } from './pages/MailDashboardPage';
import { MailInboxPage } from './pages/MailInboxPage';
import { MailReviewPage } from './pages/MailReviewPage';

type Page = 'dashboard' | 'inbox' | 'review';

const PAGE_OF_ROUTE: Record<string, Page> = {
    mail: 'dashboard',
    'mail/inbox': 'inbox',
    'mail/review': 'review',
};

const POLL_MS = 20_000;

/**
 * 메일 섹션 공통 틀.
 * - 상단 탭: 대시보드 / 메일 / 메일 검토
 * - 검토 대기열과 통계는 여기서 한 번만 불러와 각 페이지가 나눠 쓴다(탭 배지·대시보드·검토 페이지).
 */
export function MailSection({ route }: { route: string }) {
    const page = PAGE_OF_ROUTE[route] ?? 'dashboard';

    const queue = useMailList(REVIEW_STATUSES);

    const [stats, setStats] = useState<MailStats | null>(null);
    const [statsError, setStatsError] = useState(false);
    const loadStats = useCallback(async (quiet = false) => {
        try {
            setStats(await mailApi.stats());
            setStatsError(false);
        } catch {
            if (!quiet) setStats(null);
            setStatsError(true);
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadStats();
    }, [loadStats]);

    // 검토 페이지에서 편집·반려 입력 중이면 폴링을 쉰다 (목록이 바뀌어 작업이 흔들리지 않게).
    const pollPaused = useRef(false);
    const setWorking = useCallback((working: boolean) => {
        pollPaused.current = working;
    }, []);
    const { reload: reloadQueue } = queue;
    useEffect(() => {
        const id = window.setInterval(() => {
            if (pollPaused.current) return;
            void reloadQueue(true);
            void loadStats(true);
        }, POLL_MS);
        return () => window.clearInterval(id);
    }, [reloadQueue, loadStats]);

    // 통계 API가 없을 때: 목록까지 오프라인이면 예시 통계, 아니면 비워 둔다.
    const shownStats = stats ?? (queue.offline ? MOCK_STATS : null);
    const reviewCount = queue.rows.length;

    const tabs: { key: Page; label: string; path: string; count?: number }[] = [
        { key: 'dashboard', label: '대시보드', path: MAIL_PATHS.dashboard },
        { key: 'inbox', label: '전체 메일', path: MAIL_PATHS.inbox },
        { key: 'review', label: '메일 검토', path: MAIL_PATHS.review, count: reviewCount },
    ];

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader current="mail" aside={queue.offline ? <MockBadge /> : undefined}>
                <nav className="flex items-center gap-1 min-w-0 overflow-x-auto [scrollbar-width:none]">
                    {tabs.map((t) => {
                        const active = t.key === page;
                        return (
                            <a
                                key={t.key}
                                {...linkProps(t.path)}
                                aria-current={active ? 'page' : undefined}
                                className={`h-8 px-3 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-semibold whitespace-nowrap transition-colors ${
                                    active ? 'bg-chip text-ink' : 'text-muted hover:text-ink'
                                }`}
                            >
                                {t.label}
                                {t.count != null && t.count > 0 && (
                                    <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-brand text-white text-[10px] font-bold tabular-nums inline-flex items-center justify-center">
                                        {t.count}
                                    </span>
                                )}
                            </a>
                        );
                    })}
                </nav>
            </AppHeader>

            <div className="flex-1 min-h-0 flex flex-col">
                {page === 'dashboard' && <MailDashboardPage queue={queue} stats={shownStats} statsError={statsError && !shownStats} />}
                {page === 'inbox' && <MailInboxPage />}
                {page === 'review' && (
                    <MailReviewPage
                        queue={queue}
                        reloadStats={loadStats}
                        onWorkingChange={setWorking}
                    />
                )}
            </div>
        </div>
    );
}
