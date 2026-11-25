export type Server = {
  id: string;
  transport: "stdio" | "streamable_http" | "native";
  enabled?: boolean;
  command?: string;
  args?: string[];
  url?: string;
  http_allowed_hosts?: string[];
  http_allow_private?: boolean;
  allowed_tools?: string[];
  auth_ref?: string;
  native_commands?: Native[];
  max_concurrency?: number;
  call_timeout_seconds?: number;
  [key: string]: unknown;
};
export type Native = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  implementations: Record<
    string,
    {
      executable: string;
      cwd: string;
      argv: (string | { param: string })[];
      encoding?: string;
    }
  >;
  [key: string]: unknown;
};
export type User = {
  id: string;
  name: string;
  tenant_id: string;
  roles: string[];
  servers: string[];
  enabled: boolean;
  rules?: Record<string,unknown>;
  rate_limit?: number;
  secret_refs?: Record<string,string>;
};
export type State = {
  revision: number;
  generation: number;
  current_user_id?: string;
  servers: Server[];
  users: User[];
  secret_names: string[];
  health: Record<string, string>;
  platform: string;
  model: Record<string, string>;
};
export type EventRow = {
  id: number;
  created: number;
  action?: string;
  request_id?: string;
  principal_id?: string;
  server_id?: string;
  status: string;
  duration_ms?: number;
  error_code?: string;
  result_ref?: string;
};
export async function api<T = Record<string, unknown>>(
  token: string,
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求失败（${r.status}），请检查输入`,
    );
  return data;
}
