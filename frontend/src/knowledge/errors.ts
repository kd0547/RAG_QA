import { ApiError } from '../lib/http';

/** API 오류를 화면에 보여줄 문장으로 */
export function errorText(e: unknown): string {
    if (e instanceof ApiError) return e.code === 'network' ? `서버에 연결할 수 없습니다 (${e.message})` : e.message;
    return e instanceof Error ? e.message : '알 수 없는 오류가 발생했습니다.';
}
