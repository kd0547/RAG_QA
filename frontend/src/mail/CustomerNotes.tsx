import { useCallback, useEffect, useState } from 'react';
import { ApiError, customerApi } from './api';
import { fmtDateTime } from './format';
import type { CustomerNote } from './types';

const MAX_CHARS = 500;

/**
 * 고객방 오른쪽의 담당자 메모: 목록, 추가, 사용 중지. 승인·반려·편집은 여기서 하지 않는다.
 * 사용 중인 메모는 이 고객의 다음 메일을 처리할 때 답변 에이전트가 "이전 문의·메모" 도구로 볼 수 있다 (근거로 인용하지는 않는다).
 */
export function CustomerNotes({ sender, offline }: { sender: string; offline: boolean }) {
    const [notes, setNotes] = useState<CustomerNote[] | null>(null);
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showRetired, setShowRetired] = useState(false);

    const load = useCallback(async () => {
        if (offline) {
            setNotes([]);
            return;
        }
        try {
            setNotes((await customerApi.notes(sender)).items);
            setError(null);
        } catch (e) {
            setNotes([]);
            setError(e instanceof ApiError ? e.message : '메모를 불러오지 못했습니다.');
        }
    }, [sender, offline]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    const add = async () => {
        const value = text.trim();
        if (!value || busy) return;
        setBusy(true);
        setError(null);
        try {
            await customerApi.addNote(sender, value);
            setText('');
            await load();
        } catch (e) {
            setError(e instanceof ApiError ? e.message : '메모를 저장하지 못했습니다.');
        } finally {
            setBusy(false);
        }
    };

    const retire = async (note: CustomerNote) => {
        if (busy || !window.confirm('이 메모를 사용 중지할까요? 답변 에이전트에 더 이상 보이지 않습니다. (메모는 지우지 않고 남겨 둡니다)')) return;
        setBusy(true);
        setError(null);
        try {
            await customerApi.retireNote(sender, note.note_id);
            await load();
        } catch (e) {
            setError(e instanceof ApiError ? e.message : '메모를 사용 중지하지 못했습니다.');
        } finally {
            setBusy(false);
        }
    };

    const active = (notes ?? []).filter((n) => !n.retired_at);
    const retired = (notes ?? []).filter((n) => n.retired_at);
    const over = text.length > MAX_CHARS;

    return (
        <aside
            aria-label="담당자 메모"
            className="xl:w-[320px] shrink-0 min-h-0 max-h-[42vh] xl:max-h-none flex flex-col border-t xl:border-t-0 xl:border-l border-divide bg-surface/40"
        >
            <div className="shrink-0 px-4 pt-4 pb-3 border-b border-divide">
                <div className="flex items-center gap-2">
                    <h2 className="text-[14px] font-bold">담당자 메모</h2>
                    <span className="text-[12px] text-muted tabular-nums">{notes ? `${active.length}건` : ''}</span>
                </div>
                <p className="mt-1 text-[11.5px] leading-5 text-muted">
                    사용 중인 메모는 이 고객의 다음 메일을 처리할 때 답변 에이전트가 참고 자료로 볼 수 있습니다. 답변의 근거로 인용되지는 않습니다.
                </p>
                {offline ? (
                    <p className="mt-2 text-[12px] text-warn">예시 데이터에서는 메모를 남길 수 없습니다.</p>
                ) : (
                    <div className="mt-2.5">
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            rows={3}
                            disabled={busy}
                            placeholder="예: 견적은 부가세 별도로 안내 / 입찰 담당이 바뀜"
                            aria-label="새 메모"
                            className="w-full resize-y rounded-lg border border-line bg-white px-2.5 py-2 text-[12.5px] leading-5 placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand/30"
                        />
                        <div className="mt-1.5 flex items-center justify-between gap-2">
                            <span className={`text-[11px] tabular-nums ${over ? 'text-danger font-semibold' : 'text-muted'}`}>
                                {text.length} / {MAX_CHARS}
                            </span>
                            <button
                                type="button"
                                onClick={() => void add()}
                                disabled={busy || !text.trim() || over}
                                className="h-7 px-3 rounded-lg bg-brand text-white text-[12px] font-semibold hover:bg-brand-hover disabled:opacity-40"
                            >
                                {busy ? '저장 중…' : '메모 추가'}
                            </button>
                        </div>
                    </div>
                )}
                {error && <p role="alert" className="mt-2 text-[12px] text-danger">{error}</p>}
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
                {notes === null && <p className="text-[12px] text-muted">불러오는 중…</p>}
                {notes !== null && active.length === 0 && <p className="text-[12px] text-muted">사용 중인 메모가 없습니다.</p>}
                <ul className="flex flex-col gap-2">
                    {active.map((note) => (
                        <NoteItem key={note.note_id} note={note} busy={busy} onRetire={() => void retire(note)} />
                    ))}
                </ul>
                {retired.length > 0 && (
                    <div className="mt-4">
                        <button
                            type="button"
                            onClick={() => setShowRetired((v) => !v)}
                            className="text-[11.5px] font-semibold text-muted hover:text-ink"
                            aria-expanded={showRetired}
                        >
                            {showRetired ? '▾' : '▸'} 사용 중지한 메모 {retired.length}건
                        </button>
                        {showRetired && (
                            <ul className="mt-2 flex flex-col gap-2">
                                {retired.map((note) => <NoteItem key={note.note_id} note={note} busy={busy} />)}
                            </ul>
                        )}
                    </div>
                )}
            </div>
        </aside>
    );
}

function NoteItem({ note, busy, onRetire }: { note: CustomerNote; busy: boolean; onRetire?: () => void }) {
    const retired = Boolean(note.retired_at);
    return (
        <li className={`rounded-xl border px-3 py-2.5 ${retired ? 'border-divide bg-white/60 opacity-60' : 'border-line bg-white'}`}>
            <p className="text-[12.5px] leading-5 whitespace-pre-wrap break-words">{note.text}</p>
            <div className="mt-1.5 flex items-center gap-2 text-[10.5px] text-muted">
                <span className="tabular-nums">{fmtDateTime(note.created_at)}</span>
                {note.created_by && <span className="truncate">· {note.created_by}</span>}
                {retired && note.retired_at && <span className="tabular-nums">· {fmtDateTime(note.retired_at)} 사용 중지</span>}
                {onRetire && (
                    <button
                        type="button"
                        onClick={onRetire}
                        disabled={busy}
                        className="ml-auto shrink-0 h-6 px-2 rounded-md text-[11px] font-semibold text-muted hover:text-danger hover:bg-chip disabled:opacity-40"
                    >
                        사용 중지
                    </button>
                )}
            </div>
        </li>
    );
}
