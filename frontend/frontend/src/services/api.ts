/**
 * API Client - 统一的 HTTP 请求客户端
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api';

// Backend origin (without /api path) for direct resource URLs (e.g. PDF files)
export const BACKEND_URL = API_BASE.replace(/\/api\/?$/, '');

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown
  ) {
    super(`API Error: ${status} ${statusText}`);
    this.name = 'ApiError';
  }
}

async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, signal } = options;

  const config: RequestInit = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    signal,
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_BASE}${endpoint}`, config);

  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    throw new ApiError(response.status, response.statusText, data);
  }

  return response.json();
}

export const apiClient = {
  get: <T>(endpoint: string, options?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request<T>(endpoint, { method: 'GET', ...options }),

  post: <T>(endpoint: string, body?: unknown, options?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request<T>(endpoint, { method: 'POST', body, ...options }),

  put: <T>(endpoint: string, body?: unknown, options?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request<T>(endpoint, { method: 'PUT', body, ...options }),

  patch: <T>(endpoint: string, body?: unknown, options?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request<T>(endpoint, { method: 'PATCH', body, ...options }),

  delete: <T>(endpoint: string, options?: { headers?: Record<string, string>; signal?: AbortSignal }) =>
    request<T>(endpoint, { method: 'DELETE', ...options }),
};

export { ApiError };
export default apiClient;
