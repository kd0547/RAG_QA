import { useEffect, useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { request } from '../lib/http';
import { Context, empty } from './schemaContext';
import type { GraphSchema } from './schemaContext';
export function GraphSchemaProvider({ children }: { children: ReactNode }) {
    const [schema, setSchema] = useState(empty);
    const [error, setError] = useState('');
    const refresh = useCallback(() => {
        request<GraphSchema>('/graph/schema').then((s) => { setSchema(s); setError(''); })
            .catch((e: Error) => setError(e.message));
    }, []);
    useEffect(refresh, [refresh]);
    return <Context.Provider value={{ schema, refresh, error }}>{children}</Context.Provider>;
}
