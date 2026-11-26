import { useState } from 'react';
import { graphApi } from './api';
import { errorText } from './errors';

/**
 * 그래프 재구성: 등록된 모든 문서(검수 완료)에서 개체·관계를 다시 뽑는다 (POST /graph/rebuild, 백그라운드).
 * 사람이 넣은 관계와 지운 관계는 유지된다. 페이지마다 LLM을 불러 문서 양에 따라 수십 분 걸리므로 한 번 더 묻는다.
 * 용어집은 그래프에 쓰지 않으므로 재구성과 관계없다.
 */
export function RebuildButton() {
    const [state, setState] = useState<'idle' | 'confirm' | 'sending' | 'sent'>('idle');
    const [error, setError] = useState('');

    function start() {
        setState('sending');
        setError('');
        graphApi.rebuild()
            .then(() => setState('sent'))
            .catch((e: unknown) => {
                setState('idle');
                setError(errorText(e));
            });
    }

    if (state === 'sent') {
        return (
            <span role="status" className="text-[11.5px] font-semibold text-brand-hover">
                재구성을 시작했습니다. 끝나면 새로고침하세요.
                <button type="button" className="ml-2 font-semibold text-muted underline hover:text-ink" onClick={() => setState('idle')}>닫기</button>
            </span>
        );
    }

    if (state === 'confirm' || state === 'sending') {
        return (
            <span className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn-soft px-2 py-1 text-[11.5px]">
                <span className="hidden 2xl:inline text-ink">모든 문서에서 다시 뽑습니다 (수십 분, 사람이 고친 관계는 유지).</span>
                <button type="button" className="h-7 whitespace-nowrap rounded-md px-2 font-semibold text-muted hover:bg-white" onClick={() => setState('idle')} disabled={state === 'sending'}>
                    취소
                </button>
                <button type="button" title="모든 문서에서 다시 뽑습니다. 수십 분 걸리고, 사람이 고친 관계는 유지됩니다."
                    className="h-7 whitespace-nowrap rounded-md bg-brand px-2.5 font-bold text-white hover:bg-brand-hover disabled:opacity-50" onClick={start} disabled={state === 'sending'}>
                    {state === 'sending' ? '요청 중…' : '재구성 시작'}
                </button>
            </span>
        );
    }

    return (
        <span className="flex items-center gap-2">
            {error && <span role="alert" className="max-w-xs truncate text-[11.5px] text-danger" title={error}>{error}</span>}
            <button
                type="button"
                onClick={() => setState('confirm')}
                className="h-7 whitespace-nowrap rounded-lg border border-line bg-white px-2.5 text-[12px] font-semibold text-ink hover:bg-chip"
            >
                그래프 재구성
            </button>
        </span>
    );
}
