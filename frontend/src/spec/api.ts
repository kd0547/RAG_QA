/** 제품·부품 사양 API 클라이언트 (백엔드: app/routers/specs.py). 베이스 URL 규칙은 lib/http.ts 참고. */
import { API_BASE, request } from '../lib/http';

export type DataType = 'number' | 'text' | 'bool';
export type OwnerType = 'product' | 'component';

/** GET /specs/meta — 코드값과 표시 이름. 백엔드 entity/spec.py 가 기준이다 */
export interface SpecMeta {
    attribute_categories: Record<string, string>;
    data_types: Record<DataType, string>;
    product_categories: Record<string, string>;
    product_statuses: Record<string, string>;
    component_kinds: Record<string, string>;
}

export interface SpecAttribute {
    key: string;
    name: string;
    category: string;
    data_type: DataType;
    unit: string;
    description: string;
    sort_order: number;
    usage_count: number;
    created_at: string;
    updated_at: string;
}

export interface AttributeInput {
    key: string;
    name: string;
    category: string;
    data_type: DataType;
    unit: string;
    description: string;
    sort_order: number;
}

export interface SpecValue {
    id: number;
    owner_type: OwnerType;
    owner_id: string;
    attribute_key: string;
    attribute_name: string;
    category: string;
    data_type: DataType;
    unit: string;
    value_text: string;
    value_num: number | null;
    is_option: boolean;
    note: string;
    source_file_id: string | null;
    source_page: number | null;
    source_note: string;
    created_at: string;
    updated_at: string;
}

export interface SpecValueInput {
    attribute_key: string;
    value_text: string;
    is_option: boolean;
    note: string;
    source_page: number | null;
    source_note: string;
}

export interface Product {
    id: string;
    model: string;
    name: string;
    category: string;
    status: string;
    note: string;
    /** 상위 모델 id. null이면 최상위 모델 */
    parent_id: string | null;
    spec_count: number;
    component_count: number;
    child_count: number;
    created_at: string;
    updated_at: string;
}

export interface ProductInput {
    model: string;
    name: string;
    category: string;
    status: string;
    note: string;
    parent_id: string | null;
}

export interface ProductRef {
    id: string;
    model: string;
}

export interface LinkedComponent {
    id: string;
    kind: string;
    model: string;
    vendor: string;
    note: string;
    is_option: boolean;
    link_note: string;
}

export interface ProductDetail extends Product {
    specs: SpecValue[];
    components: LinkedComponent[];
    /** 최상위 모델부터 바로 위 모델까지 */
    ancestors: ProductRef[];
    /** 바로 아래 하위(파생) 모델 */
    children: (ProductRef & { name: string; status: string })[];
}

export interface Component {
    id: string;
    kind: string;
    model: string;
    vendor: string;
    note: string;
    spec_count: number;
    product_count: number;
    created_at: string;
    updated_at: string;
}

export interface ComponentInput {
    kind: string;
    model: string;
    vendor: string;
    note: string;
}

export interface ComponentDetail extends Component {
    specs: SpecValue[];
    products: { id: string; model: string; name: string; is_option: boolean }[];
}

// ---------- 표 가져오기 ----------

export interface ImportPreviewValue {
    value_text: string;
    is_option: boolean;
    error: string | null;
}

export interface ImportPreviewCell {
    column: number;
    raw: string;
    values: ImportPreviewValue[];
}

export interface ImportPreviewRow {
    index: number;
    label: string;
    attribute_key: string | null;
    match: 'key' | 'name' | 'alias' | null;
    /** 사전에 아직 없는 기본 속성에 맞은 행. 적용할 때 이 속성을 새로 만든다 */
    new_attribute: ImportNewAttribute | null;
    cells: ImportPreviewCell[];
}

export interface ImportPreviewColumn {
    index: number;
    header: string;
    owner_id: string | null;
    owner_label: string | null;
    /** 제품 표의 '상위 모델' 행 값. 있으면 그 모델의 하위(파생) 모델로 등록한다 */
    parent_model: string | null;
    /** 제품 표의 '제품 이름' 행 값 */
    name: string | null;
}

export interface ImportPreview {
    owner_type: OwnerType;
    kind: string | null;
    source: string;
    columns: ImportPreviewColumn[];
    rows: ImportPreviewRow[];
    skipped_columns: string[];
    unmatched_rows: number;
    /** 이미지(화면 캡처)를 읽은 경우 VLM이 인식한 표 텍스트. 붙여넣기 칸에 넣어 고쳐 다시 읽을 수 있다 */
    recognized_text?: string | null;
}

export interface ImportNewAttribute {
    key: string;
    name: string;
    category: string;
    data_type: DataType;
    unit: string;
    description: string;
}

export interface ImportBody {
    owner_type: OwnerType;
    kind: string | null;
    replace: boolean;
    source_note: string;
    source_page: number | null;
    columns: { header: string; owner_id: string | null; create: boolean; skip: boolean; parent_model?: string | null; name?: string | null }[];
    rows: { attribute_key: string | null; new_attribute: ImportNewAttribute | null; cells: string[] }[];
}

export interface ImportSummary {
    owners_created: number;
    /** 상위 모델을 맞춘 제품 수 */
    parents_set?: number;
    attributes_created: number;
    values_added: number;
    values_replaced: number;
    rows_skipped: number;
    owners: string[];
}

/** 적용 실패(400) 때 서버가 주는 셀별 오류. row/column은 보낸 rows/columns의 순번 */
export interface ImportError {
    row: number | null;
    column: number | null;
    message: string;
}

const enc = encodeURIComponent;
const json = (method: 'POST' | 'PUT', body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const specApi = {
    meta(): Promise<SpecMeta> {
        return request<SpecMeta>('/specs/meta');
    },

    // 속성 사전
    listAttributes(): Promise<SpecAttribute[]> {
        return request<SpecAttribute[]>('/specs/attributes');
    },
    createAttribute(input: AttributeInput): Promise<SpecAttribute> {
        return request<SpecAttribute>('/specs/attributes', json('POST', input));
    },
    updateAttribute(key: string, patch: Partial<Omit<AttributeInput, 'key'>>): Promise<SpecAttribute> {
        return request<SpecAttribute>(`/specs/attributes/${enc(key)}`, json('PUT', patch));
    },
    deleteAttribute(key: string): Promise<void> {
        return request<void>(`/specs/attributes/${enc(key)}`, { method: 'DELETE' });
    },
    /** 서버에 정의된 기본 속성 중 없는 것만 넣는다 */
    addDefaultAttributes(): Promise<{ added: number }> {
        return request<{ added: number }>('/specs/attributes/defaults', { method: 'POST' });
    },

    // 제품
    listProducts(): Promise<Product[]> {
        return request<Product[]>('/specs/products');
    },
    getProduct(id: string): Promise<ProductDetail> {
        return request<ProductDetail>(`/specs/products/${enc(id)}`);
    },
    createProduct(input: ProductInput): Promise<ProductDetail> {
        return request<ProductDetail>('/specs/products', json('POST', input));
    },
    updateProduct(id: string, input: ProductInput): Promise<ProductDetail> {
        return request<ProductDetail>(`/specs/products/${enc(id)}`, json('PUT', input));
    },
    deleteProduct(id: string): Promise<void> {
        return request<void>(`/specs/products/${enc(id)}`, { method: 'DELETE' });
    },
    /** 제품에 부품을 넣거나 옵션 여부를 바꾼다. 바뀐 제품 상세가 온다 */
    linkComponent(productId: string, link: { component_id: string; is_option: boolean; note: string }): Promise<ProductDetail> {
        return request<ProductDetail>(`/specs/products/${enc(productId)}/components`, json('PUT', link));
    },
    unlinkComponent(productId: string, componentId: string): Promise<ProductDetail> {
        return request<ProductDetail>(`/specs/products/${enc(productId)}/components/${enc(componentId)}`, { method: 'DELETE' });
    },

    // 부품
    listComponents(): Promise<Component[]> {
        return request<Component[]>('/specs/components');
    },
    getComponent(id: string): Promise<ComponentDetail> {
        return request<ComponentDetail>(`/specs/components/${enc(id)}`);
    },
    createComponent(input: ComponentInput): Promise<ComponentDetail> {
        return request<ComponentDetail>('/specs/components', json('POST', input));
    },
    updateComponent(id: string, input: ComponentInput): Promise<ComponentDetail> {
        return request<ComponentDetail>(`/specs/components/${enc(id)}`, json('PUT', input));
    },
    deleteComponent(id: string): Promise<void> {
        return request<void>(`/specs/components/${enc(id)}`, { method: 'DELETE' });
    },

    // 표 가져오기
    templateUrl(ownerType: OwnerType, kind: string | null): string {
        const query = new URLSearchParams({ owner_type: ownerType });
        if (kind) query.set('kind', kind);
        return `${API_BASE}/specs/import/template?${query.toString()}`;
    },
    parseImport(input: { owner_type: OwnerType; kind: string | null; text?: string; file?: File | null }): Promise<ImportPreview> {
        const form = new FormData();
        form.append('owner_type', input.owner_type);
        if (input.kind) form.append('kind', input.kind);
        if (input.text) form.append('text', input.text);
        if (input.file) form.append('file', input.file);
        return request<ImportPreview>('/specs/import/parse', { method: 'POST', body: form });
    },
    applyImport(body: ImportBody): Promise<ImportSummary> {
        return request<ImportSummary>('/specs/import/apply', json('POST', body));
    },

    // 사양 값 (제품·부품 공통)
    addValue(owner: { owner_type: OwnerType; owner_id: string }, input: SpecValueInput): Promise<SpecValue> {
        return request<SpecValue>('/specs/values', json('POST', { ...owner, ...input }));
    },
    updateValue(id: number, patch: Partial<SpecValueInput>): Promise<SpecValue> {
        return request<SpecValue>(`/specs/values/${id}`, json('PUT', patch));
    },
    deleteValue(id: number): Promise<void> {
        return request<void>(`/specs/values/${id}`, { method: 'DELETE' });
    },
};
