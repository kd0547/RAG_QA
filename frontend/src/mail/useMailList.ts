import { useCallback, useEffect, useState } from 'react';
import { ApiError, mailApi } from './api';
import { mockList } from './mockData';
import type { MailStatus, MailSummary } from './types';

/**
 * GET /mails 목록 로더. 실패하면 예시 데이터로 폴백하고 offline 을 켠다.
 * quiet 로드(폴링)는 실패해도 화면을 건드리지 않는다.
 */
export function useMailList(statuses: readonly MailStatus[], q = '') {
    const [rows, setRows] = useState<MailSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [offline, setOffline] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // 배열은 렌더마다 새로 만들어지므로 문자열 키로 의존성을 고정한다.
    const statusKey = statuses.join(',');

    const reload = useCallback(
        async (quiet = false) => {
            const wanted = statusKey.split(',') as MailStatus[];
            try {
                const list = await mailApi.list({ status: wanted, q: q || undefined, order: '-received_at', limit: 200 });
                setRows(list.items);
                setOffline(false);
                setError(null);
            } catch (e) {
                if (quiet) return;
                setRows(mockList(wanted, q));
                setOffline(true);
                setError(e instanceof ApiError && e.code !== 'network' ? e.message : null);
            } finally {
                if (!quiet) setLoading(false);
            }
        },
        [statusKey, q],
    );

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void reload();
    }, [reload]);

    return { rows, setRows, loading, offline, error, reload };
}

export type MailList = ReturnType<typeof useMailList>;
