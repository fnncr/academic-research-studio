export type Task = { request_id: string; section_id?: string | null; brief_revision_id: string; manuscript_revision_id: string; plan_revision_id: string; claim_ids: string[]; title: string; instruction: string; max_output_tokens: number; provider: 'mock'|'openai'; model: 'mock-grounded-v1'|'gpt-4.1-mini-2025-04-14' };
export type Job = { id: string; state: string; task?: Task; result?: { paragraphs?: string[]; research_gaps?: { explanation: string }[]; warnings?: string[]; citations?: unknown[] }; report?: { semantic?: string }; charged_units?: number | null; held_units?: number; cancel_requested: boolean; acceptance?: { manuscript_revision_id: string } | null };
export type Preview = { fingerprint: string; input: { task: Task; quote: { max_units: number; input_token_bound: number; output_token_cap: number }; context: unknown; disclosure: string } };
export type Pending = { task?: Task; fingerprint?: string; jobId?: string; accept?: Record<string, unknown>; cancel?: Record<string, unknown> };
export const storageKey = (project: string) => `research-assistant:v1:${project}`;
export function restore(project: string): Pending { try { const value = JSON.parse(sessionStorage.getItem(storageKey(project)) ?? '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; } catch { return {}; } }
export function persist(project: string, value: Pending) { sessionStorage.setItem(storageKey(project), JSON.stringify(value)); }
export async function modelApi<T>(path: string, token: string, body?: unknown, method = 'POST'): Promise<T> {
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, { signal: controller.signal, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { method, body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok && ['provider_configuration_unavailable','call_budget_exceeded'].includes(data.detail?.code)) throw new Error('Внешний провайдер отключён: нужны отдельный ключ приложения, согласование данных/тарифа и достаточный предел расходов.');
    if (!response.ok) throw new Error(response.status === 409 ? 'Конфликт состояния или версий. Автоматического применения нет; проверьте актуальные версии.' : response.status === 401 ? 'Проверьте ключ владельца.' : response.status === 503 ? 'Помощник недоступен. Ручной редактор продолжает работать.' : data.detail?.message ?? 'Ошибка API помощника.');
    return data;
  } catch (e) { if (e instanceof Error && e.name === 'AbortError') throw new Error('Ответ неизвестен. Повторяйте тот же запрос с сохранённым UUID; новое задание автоматически не создаётся.'); throw e; }
  finally { clearTimeout(timeout); }
}
export async function sha256(value: unknown) {
  const canonical = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : v && typeof v === 'object' ? `{${Object.entries(v).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0).map(([k,x]) => JSON.stringify(k)+':'+canonical(x)).join(',')}}` : JSON.stringify(v);
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(value)));
  return [...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,'0')).join('');
}
