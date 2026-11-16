import { request } from '../lib/http';

/**
 * UUID v4. crypto.randomUUID는 https·localhost(보안 컨텍스트)에서만 있어서,
 * http로 여는 서버(예: http://…:9092)에서는 crypto.getRandomValues로 같은 형식을 만든다.
 */
function newId(): string {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** All graph writes carry an unauthenticated session label and an idempotency key. */
export function graphWrite<T>(path: string, method: string, data?: unknown): Promise<T> {
    let session = sessionStorage.getItem('graph-edit-session');
    if (!session) {
        session = newId();
        sessionStorage.setItem('graph-edit-session', session);
    }
    return request<T>(`/graph${path}`, {
        method, body: data === undefined ? undefined : JSON.stringify(data),
        headers: {
            'Idempotency-Key': newId(), 'X-Graph-Session': session,
            'X-Graph-Actor': encodeURIComponent(sessionStorage.getItem('graph-edit-actor') ?? ''),
        },
    });
}
