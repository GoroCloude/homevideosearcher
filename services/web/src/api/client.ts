/** Read settings from localStorage (not React context — usable inside queryFn). */
export function getSettings() {
  return {
    apiBaseUrl: localStorage.getItem('hvs:api_base_url') ?? '',
    apiToken:   localStorage.getItem('hvs:api_token')   ?? '',
  };
}

/**
 * Authenticated fetch wrapper.
 * - Injects Authorization: Bearer header from localStorage token.
 * - Uses nginx /api proxy by default (empty apiBaseUrl).
 * - Throws on non-2xx responses (message includes status + body for debugging).
 * - Do NOT set Content-Type for FormData requests (pass it in options.headers to override).
 */
export async function authFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const { apiBaseUrl, apiToken } = getSettings();
  const prefix = apiBaseUrl || '/api';   // empty = nginx /api/ proxy

  const isFormData = options.body instanceof FormData;
  const headers: HeadersInit = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
    ...(options.headers ?? {}),
  };

  const response = await fetch(`${prefix}${path}`, { ...options, headers });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
  return response;
}
