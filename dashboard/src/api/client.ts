export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message?: string) {
    super(message ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(
  path: string,
  token: string,
  onUnauthorized: () => void,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    onUnauthorized();
    throw new ApiError(401);
  }
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return response;
}

export async function fetchJson<T>(
  path: string,
  token: string,
  onUnauthorized: () => void,
  init?: RequestInit,
): Promise<T> {
  const response = await request(path, token, onUnauthorized, init);
  return (await response.json()) as T;
}

export async function fetchBlob(
  path: string,
  token: string,
  onUnauthorized: () => void,
  init?: RequestInit,
): Promise<Blob> {
  const response = await request(path, token, onUnauthorized, init);
  return response.blob();
}
