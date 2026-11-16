import { request } from '../lib/http';

/** All graph writes carry an unauthenticated session label and an idempotency key. */
export function graphWrite<T>(path: string, method: string, data?: unknown): Promise<T> {
    let session = sessionStorage.getItem('graph-edit-session');
    if (!session) {
        session = crypto.randomUUID();
        sessionStorage.setItem('graph-edit-session', session);
    }
    return request<T>(`/graph${path}`, {
        method, body: data === undefined ? undefined : JSON.stringify(data),
        headers: {
            'Idempotency-Key': crypto.randomUUID(), 'X-Graph-Session': session,
            'X-Graph-Actor': encodeURIComponent(sessionStorage.getItem('graph-edit-actor') ?? ''),
        },
    });
}
