import type { Revision } from './manuscript';
import type { SourceVersion } from './sources';
export type Range = { start: number; end: number; quote: string };
export type EvidenceContent = { excerpt: string; selection: Range; locator: { kind: 'page' | 'section' | 'paragraph'; label: string }; material: 'abstract' | 'full_text_excerpt'; note: string; rights_confirmed: boolean; original_language?: string };
export type Evidence = { id: string; source_version_id: string; content: EvidenceContent; source_version?: SourceVersion; verification: string; locator_verification: string; full_text_verified: boolean };
export type Link = { evidence_id: string; relation: 'supports' | 'contradicts' | 'limits'; rationale: string };
export type Claim = { id: string; statement: string; section_id: string | null; evidence: Link[] };
export type Citation = { id: string; claim_id: string; evidence_id: string; block_id: string; selection: Range; kind: 'quotation' | 'paraphrase' };
export type PlanDocument = { schema_version: '1'; claims: Claim[]; citations: Citation[] };
export type Plan = { id: string; number: number; manuscript_revision_id: string; document: PlanDocument; created_at: string };
export const emptyPlan = (): PlanDocument => ({ schema_version: '1', claims: [], citations: [] });
export const relations = { supports: 'Подтверждает', contradicts: 'Противоречит', limits: 'Ограничивает применимость' };
export function textNodes(revision: Revision) {
  const nodes: { id: string; text: string; type?: string }[] = [];
  function visit(value: unknown) {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') {
      const item = value as { id?: string; text?: string; type?: string };
      if (item.id && typeof item.text === 'string') nodes.push({ id: item.id, text: item.text, type: item.type });
      Object.values(value).filter(v => v && typeof v === 'object').forEach(visit);
    }
  }
  visit(revision.document); return nodes;
}
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options); const data = await response.json();
  if (!response.ok) throw new ApiError(data.detail?.message ?? 'Не удалось выполнить запрос.', response.status);
  return data;
}
export const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
