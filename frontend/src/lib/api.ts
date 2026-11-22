// Cliente HTTP: sempre via /api (mesma origem), envia cookie de sessão e o header CSRF (double-submit).
export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  data: Record<string, unknown>;
  constructor(status: number, body: Record<string, unknown>) {
    super(typeof body.detail === 'string' ? body.detail : 'Não foi possível concluir a operação.');
    this.status = status;
    this.code = String(body.code || 'error');
    this.fields = (body.fields as Record<string, string>) || {};
    this.data = body;
  }
}

export function csrfToken(): string {
  if (typeof document === 'undefined') return '';
  const m = document.cookie.match(/(?:^|; )lp_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  }
  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET') headers.set('X-CSRF-Token', csrfToken());
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, method, headers, body, credentials: 'same-origin', cache: 'no-store' });
  } catch {
    throw new ApiError(0, { detail: 'Sem conexão com o servidor. Verifique sua internet.', code: 'network' });
  }
  const text = await res.text();
  let data: Record<string, unknown> = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export const get = <T,>(p: string) => api<T>(p);
export const post = <T,>(p: string, json?: unknown) => api<T>(p, { method: 'POST', json: json ?? {} });
export const put = <T,>(p: string, json?: unknown) => api<T>(p, { method: 'PUT', json: json ?? {} });
export const patch = <T,>(p: string, json?: unknown) => api<T>(p, { method: 'PATCH', json: json ?? {} });
export const del = <T,>(p: string) => api<T>(p, { method: 'DELETE' });
