import { useState } from "react";
import {
  Activity,
  ArrowRight,
  Box,
  CheckCircle2,
  ChevronRight,
  Copy,
  FileClock,
  Globe,
  KeyRound,
  LayoutDashboard,
  Loader2,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server as ServerIcon,
  Settings2,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  Users,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  type State,
  type Server,
  type User,
  type EventRow,
} from "@/lib/api";
import { ServerEditor } from "@/components/ServerEditor";
import { Operations } from "@/components/Operations";

const nav = [
  ["overview", "概览", LayoutDashboard],
  ["servers", "服务与工具", Box],
  ["users", "用户与授权", Users],
  ["model", "模型与凭证", Sparkles],
  ["playground", "调用工作台", Terminal],
  ["events", "调用记录", FileClock],
  ["operations", "治理与运维", ShieldCheck],
] as const;
type Page = (typeof nav)[number][0];
const labels = {
  stdio: "本地 MCP",
  streamable_http: "远程 MCP",
  native: "原生命令",
};
function Status({
  online,
  disabled = false,
}: {
  online: boolean;
  disabled?: boolean;
}) {
  return (
    <span className={`pill ${online && !disabled ? "" : "offline"}`}>
      <i className="dot" />
      {disabled ? "已停用" : online ? "运行正常" : "未就绪"}
    </span>
  );
}
export default function App() {
  const [token, setToken] = useState(""),
    [login, setLogin] = useState(""),
    [state, setState] = useState<State | null>(null),
    [page, setPage] = useState<Page>("overview"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [events, setEvents] = useState<EventRow[]>([]);
  const [editor, setEditor] = useState<Server | null | undefined>(undefined),
    [filter, setFilter] = useState(""),
    [search, setSearch] = useState(""),
    [probe, setProbe] = useState<{
      server: Server;
      tools: { name: string; description: string; input_schema: object }[];
    } | null>(null),
    [selected, setSelected] = useState<string[]>([]);
  const [userEditor, setUserEditor] = useState<User | null | undefined>(
      undefined,
    ),
    [issued, setIssued] = useState(""),
    [confirm, setConfirm] = useState<{
      title: string;
      run: () => Promise<void>;
    } | null>(null),
    [detail, setDetail] = useState<unknown>(null);
  const [command, setCommand] = useState("ls /mcp"),
    [session, setSession] = useState(""),
    [output, setOutput] = useState<unknown>(null),
    [setup, setSetup] = useState(false),
    [agentTask, setAgentTask] = useState(""),
    [agentOutput, setAgentOutput] = useState<unknown>(null);
  async function refresh(t = token) {
    const data = await api<State>(t, "/api/admin/state");
    setState(data);
    setEvents(
      (await api<{ events: EventRow[] }>(t, "/api/admin/events")).events,
    );
    return data;
  }
  async function action(fn: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function mutate(path: string, value: unknown, method = "PUT") {
    const data = await api<State & { issued_token?: string }>(
      token,
      path,
      method,
      { revision: state!.revision, value },
    );
    setSession("");
    let activeToken = token;
    if (data.issued_token) {
      setIssued(data.issued_token);
      if (path === `/api/admin/users/${state!.current_user_id}/rotate`) {
        activeToken = data.issued_token;
        setToken(activeToken);
      }
    }
    await refresh(activeToken);
    setNotice(
      "配置已校验并应用。运行实例已切换，工作台会话将在下次调用时重新创建。",
    );
    return data;
  }
  async function saveServer(s: Server) {
    await mutate(`/api/admin/servers/${s.id}`, s);
  }
  async function testServer(s: Server) {
    await action(async () => {
      const data = await api<{
        tools: { name: string; description: string; input_schema: object }[];
      }>(token, `/api/admin/servers/${s.id}/probe`, "POST");
      setProbe({ server: s, tools: data.tools });
      setSelected(s.allowed_tools ?? []);
      await refresh();
    });
  }
  async function execute() {
    await action(async () => {
      let sid = session;
      if (!sid) {
        sid = (
          await api<{ session_id: string }>(
            token,
            "/api/v1/sessions",
            "POST",
            {},
          )
        ).session_id;
        setSession(sid);
      }
      const result = await api(token, "/api/v1/shell/execute", "POST", {
        session_id: sid,
        command,
      });
      setOutput(result);
      setEvents(
        (await api<{ events: EventRow[] }>(token, "/api/admin/events")).events,
      );
    });
  }
  function logout() {
    setToken("");
    setState(null);
    setSession("");
    setOutput(null);
    setLogin("");
  }
  if (!state)
    return (
      <main className="auth">
        <section className="auth-card">
          <div className="row">
            <div className="iconbox bg-indigo-600 text-white">
              <Terminal size={23} />
            </div>
            <strong className="text-xl tracking-tight">
              MVS <span className="text-slate-400 font-normal">Console</span>
            </strong>
          </div>
          <p className="eyebrow mt-9">YOUR TOOLS, ONE PLACE</p>
          <h1 className="text-2xl font-semibold mt-3 mb-3">连接你的工具世界</h1>
          <p className="text-slate-500 text-sm leading-6 mb-7">
            管理 MCP 服务、原生命令与 Agent 授权。
            <br />
            使用本机生成的管理员令牌登录。
          </p>
          {error && (
            <div role="alert" className="notice error">
              {error}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action(async () => {
                await refresh(login);
                setToken(login);
                setLogin("");
              });
            }}
          >
            <label htmlFor="login-token" className="text-xs font-medium">
              管理员令牌
            </label>
            <Input
              id="login-token"
              type="password"
              autoComplete="off"
              className="mt-2 mb-4 h-11"
              placeholder="粘贴管理员令牌"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              required
            />
            <Button type="submit" className="w-full h-11" disabled={busy}>
              {busy ? (
                <Loader2 className="animate-spin" size={16} />
              ) : (
                <>
                  进入控制台 <ArrowRight size={16} />
                </>
              )}
            </Button>
          </form>
          <div className="rounded-lg bg-slate-50 p-4 mt-6 text-xs text-slate-500 leading-6">
            第一次使用？在终端运行
            <br />
            <code className="text-slate-700">mvs init</code>，然后用{" "}
            <code className="text-slate-700">mvs token show</code> 查看令牌。
          </div>
          <p className="text-[11px] text-slate-400 mt-7 text-center">
            令牌只保留在当前页面内存中 · 不写入浏览器存储
          </p>
        </section>
      </main>
    );
  const online = state.servers.filter(
    (s) => state.health[s.id] === "online" && s.enabled !== false,
  ).length;
  const tools = state.servers.reduce(
    (n, s) => n + (s.allowed_tools?.length ?? 0),
    0,
  );
  const current = nav.find((n) => n[0] === page)!;
  const visible = state.servers.filter(
    (s) =>
      (!filter || s.transport === filter) &&
      `${s.id} ${labels[s.transport]}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <aside className="sidebar">
        <div className="row px-2">
          <div className="iconbox !w-8 !h-8 bg-indigo-600 text-white">
            <Terminal size={19} />
          </div>
          <span className="brand-text font-bold text-xl tracking-tight">
            MVS
            <span className="ml-2 text-[10px] rounded bg-slate-100 text-slate-500 px-1.5 py-1 align-middle tracking-normal">
              CONSOLE
            </span>
          </span>
        </div>
        <div className="nav-caption">工作空间</div>
        {nav.map(([id, label, Icon]) => (
          <button
            key={id}
            className={`navitem ${page === id ? "active" : ""}`}
            onClick={() => {
              setPage(id);
              setError("");
              setNotice("");
            }}
            title={label}
          >
            <Icon size={18} />
            <span className="nav-text">{label}</span>
            {page === id && (
              <ChevronRight size={13} className="ml-auto nav-text" />
            )}
          </button>
        ))}
        <div className="mt-auto border-t pt-5">
          <div className="row px-3 mb-4">
            <div className="w-8 h-8 rounded-full bg-indigo-50 text-indigo-600 grid place-items-center text-xs font-semibold">
              AD
            </div>
            <div className="bottom-text">
              <div className="text-xs font-semibold">本机管理员</div>
              <div className="text-[10px] text-slate-400 mt-1">
                配置版本 v{state.revision}
              </div>
            </div>
          </div>
          <button className="navitem" onClick={logout} title="退出登录">
            <LogOut size={16} />
            <span className="nav-text text-xs">退出登录</span>
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="row text-xs text-slate-400">
            <span>MVS 工作空间</span>
            <ChevronRight size={12} />
            <span className="text-slate-700">{current[1]}</span>
          </div>
          <div className="row">
            <span className="subtle">本地实例 · {state.platform}</span>
            <span className="pill">
              <i className="dot" />
              已连接
            </span>
          </div>
        </header>
        <main className="content">
          <div className="page-head">
            <div>
              <div className="eyebrow">CONTROL CENTER</div>
              <h1>
                {page === "overview" ? "所有工具，一处掌控。" : current[1]}
              </h1>
              <p>
                {page === "overview"
                  ? "连接服务、配置权限，让 Agent 有序地使用工具。"
                  : page === "servers"
                    ? "管理 MCP 连接和本机原生命令，按需开放工具。"
                    : page === "users"
                      ? "按主体分配服务授权，创建和轮换访问令牌。"
                      : page === "model"
                        ? "配置 Responses 模型接口与受控凭证引用。"
                        : page === "playground"
                          ? "使用当前管理员身份执行受限命令，查看真实结果。"
                          : "查看最近的配置变更和执行结果，不记录原始参数。"}
              </p>
            </div>
            <div className="row">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await refresh();
                  })
                }
              >
                <RefreshCw size={14} />
                刷新
              </Button>
              {(page === "overview" || page === "servers") && (
                <Button size="sm" onClick={() => setEditor(null)}>
                  <Plus size={15} />
                  添加服务
                </Button>
              )}
              {page === "users" && (
                <Button size="sm" onClick={() => setUserEditor(null)}>
                  <Plus size={15} />
                  添加用户
                </Button>
              )}
            </div>
          </div>
          {error && (
            <div role="alert" className="notice error">
              {error}
            </div>
          )}
          {notice && (
            <div role="status" className="notice">
              {notice}
            </div>
          )}
          {page === "overview" && (
            <>
              <div className="grid-stats">
                {[
                  [
                    ServerIcon,
                    "已连接服务",
                    `${online}`,
                    `共 ${state.servers.length} 个已配置服务`,
                  ],
                  [Box, "已开放工具", `${tools}`, "仅白名单中的工具可执行"],
                  [
                    Users,
                    "访问主体",
                    `${state.users.filter((u) => u.enabled).length}`,
                    "按用户与租户隔离",
                  ],
                  [
                    Activity,
                    "最近调用",
                    `${events.filter((e) => e.request_id).length}`,
                    "最近 100 条记录中的调用",
                  ],
                ].map(([Icon, label, value, desc]) => (
                  <Card
                    key={String(label)}
                    className="shadow-none border-slate-200/80"
                  >
                    <CardContent className="p-5">
                      <div className="flex justify-between text-slate-500 text-xs">
                        <span>{String(label)}</span>
                        <Icon size={16} className="text-slate-400" />
                      </div>
                      <div className="stat-value">{String(value)}</div>
                      <div className="subtle">{String(desc)}</div>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <div className="panel mt-6 p-6 flex flex-wrap items-center justify-between gap-5 bg-gradient-to-r from-indigo-50/60 to-white">
                <div className="row">
                  <div className="iconbox bg-indigo-100">
                    <Sparkles size={22} />
                  </div>
                  <div>
                    <h2 className="section-title">几步，准备好你的工作空间</h2>
                    <p className="subtle mt-1.5">
                      连接模型 → 注册服务 → 分配授权，开始第一次工具调用。
                    </p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  className="bg-white"
                  onClick={() => setSetup(true)}
                >
                  打开配置向导 <ArrowRight size={14} />
                </Button>
              </div>
              <div className="two-col mt-6">
                <section className="panel">
                  <div className="panel-header">
                    <h2 className="section-title">
                      服务状态{" "}
                      <span className="ml-2 tag">{state.servers.length}</span>
                    </h2>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setPage("servers")}
                    >
                      管理全部 <ArrowRight size={13} />
                    </Button>
                  </div>
                  {state.servers.length ? (
                    state.servers.slice(0, 5).map((s) => (
                      <div
                        key={s.id}
                        className="flex items-center justify-between px-6 py-5 border-b last:border-0"
                      >
                        <div className="row">
                          <div className="iconbox !w-9 !h-9">
                            {s.transport === "native" ? (
                              <Terminal size={17} />
                            ) : s.transport === "streamable_http" ? (
                              <Globe size={17} />
                            ) : (
                              <ServerIcon size={17} />
                            )}
                          </div>
                          <div>
                            <div className="text-sm font-semibold">{s.id}</div>
                            <div className="subtle mt-1">
                              {labels[s.transport]} ·{" "}
                              {s.allowed_tools?.length ?? 0} 个开放工具
                            </div>
                          </div>
                        </div>
                        <Status
                          online={state.health[s.id] === "online"}
                          disabled={s.enabled === false}
                        />
                      </div>
                    ))
                  ) : (
                    <div className="empty">
                      还没有服务，点击「添加服务」开始。
                    </div>
                  )}
                </section>
                <section className="panel">
                  <div className="panel-header">
                    <h2 className="section-title">快速开始</h2>
                    <span className="tag">GUIDE</span>
                  </div>
                  {[
                    [
                      Box,
                      "连接 MCP 服务",
                      "从本地进程或远程端点发现工具",
                      "servers",
                    ],
                    [
                      Terminal,
                      "开放系统命令",
                      "用固定程序和参数绑定管理原生命令",
                      "servers",
                    ],
                    [
                      ShieldCheck,
                      "分配访问权限",
                      "创建普通用户并授权服务组",
                      "users",
                    ],
                  ].map(([Icon, title, desc, target]) => (
                    <button
                      key={String(title)}
                      onClick={() => setPage(target as Page)}
                      className="w-full flex gap-3 text-left px-6 py-5 border-b last:border-0 hover:bg-slate-50"
                    >
                      <Icon size={18} className="text-slate-400 mt-0.5" />
                      <span className="flex-1">
                        <span className="text-sm font-medium">
                          {String(title)}
                        </span>
                        <span className="block subtle mt-1">
                          {String(desc)}
                        </span>
                      </span>
                      <ChevronRight size={15} className="text-slate-300 mt-1" />
                    </button>
                  ))}
                </section>
              </div>
              <section className="panel mt-6">
                <div className="panel-header">
                  <h2 className="section-title">最近活动</h2>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPage("events")}
                  >
                    全部记录 <ArrowRight size={13} />
                  </Button>
                </div>
                <EventTable
                  rows={events.slice(0, 5)}
                  onResult={(ref) =>
                    action(async () =>
                      setDetail(
                        await api(
                          token,
                          `/api/admin/result?ref=${encodeURIComponent(ref)}`,
                        ),
                      ),
                    )
                  }
                />
              </section>
            </>
          )}
          {page === "servers" && (
            <>
              <div className="toolbar">
                <div className="relative flex-1 max-w-sm">
                  <Search
                    size={15}
                    className="absolute left-3 top-3 text-slate-400"
                  />
                  <Input
                    className="pl-9 bg-white"
                    aria-label="搜索服务"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="搜索服务名称…"
                  />
                </div>
                <select
                  className="form-select !w-36"
                  aria-label="服务类型"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="">全部类型</option>
                  <option value="stdio">本地 MCP</option>
                  <option value="streamable_http">远程 MCP</option>
                  <option value="native">原生命令</option>
                </select>
                <span className="subtle ml-auto">{visible.length} 个服务</span>
              </div>
              <div className="server-grid">
                {visible.map((s) => (
                  <section key={s.id} className="panel p-5">
                    <div className="flex justify-between">
                      <div className="iconbox">
                        {s.transport === "native" ? (
                          <Terminal size={20} />
                        ) : s.transport === "streamable_http" ? (
                          <Globe size={20} />
                        ) : (
                          <ServerIcon size={20} />
                        )}
                      </div>
                      <Switch
                        aria-label={`启停 ${s.id}`}
                        checked={s.enabled !== false}
                        disabled={busy}
                        onCheckedChange={(enabled) =>
                          action(async () => saveServer({ ...s, enabled }))
                        }
                      />
                    </div>
                    <h2 className="text-base font-semibold mt-5">{s.id}</h2>
                    <div className="flex justify-between items-center mt-2">
                      <span className="subtle">{labels[s.transport]}</span>
                      <Status
                        online={state.health[s.id] === "online"}
                        disabled={s.enabled === false}
                      />
                    </div>
                    <div className="rounded-md bg-slate-50 font-mono text-[11px] text-slate-500 px-3 py-2.5 mt-4 truncate">
                      {s.transport === "native"
                        ? `/os/${s.id}/tools`
                        : (s.url ??
                          `${s.command ?? ""} ${(s.args ?? []).join(" ")}`)}
                    </div>
                    <div className="flex justify-between text-xs text-slate-400 mt-4 pb-4 border-b">
                      <span>{s.allowed_tools?.length ?? 0} 个开放工具</span>
                      <span>
                        并发 {s.max_concurrency ?? 2} ·{" "}
                        {s.call_timeout_seconds ?? 15}s 超时
                      </span>
                    </div>
                    <div className="flex gap-2 mt-4">
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1"
                        disabled={busy || s.enabled === false}
                        onClick={() => testServer(s)}
                      >
                        <Zap size={13} />
                        连接与工具
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditor(s)}
                        aria-label={`编辑 ${s.id}`}
                      >
                        <Settings2 size={15} />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`删除 ${s.id}`}
                        onClick={() =>
                          setConfirm({
                            title: `删除服务 ${s.id}？相关用户授权也会移除。`,
                            run: async () => {
                              await mutate(
                                `/api/admin/servers/${s.id}`,
                                {},
                                "DELETE",
                              );
                            },
                          })
                        }
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </section>
                ))}
              </div>
              {!visible.length && (
                <div className="panel empty">
                  没有匹配的服务。可以添加一个 MCP 服务或原生命令组。
                </div>
              )}
            </>
          )}
          {page === "users" && (
            <section className="panel">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">用户</TableHead>
                    <TableHead>角色 / 租户</TableHead>
                    <TableHead>服务授权</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right pr-6">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {state.users.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="pl-6 py-5">
                        <strong>{u.name}</strong>
                        <div className="subtle mt-1">{u.id}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">
                          {u.roles.includes("admin") ? "管理员" : "普通用户"}
                        </Badge>
                        <div className="subtle mt-1">{u.tenant_id}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {u.servers.map((s) => (
                            <Badge variant="outline" key={s}>
                              {s}
                            </Badge>
                          ))}
                          {!u.servers.length && (
                            <span className="subtle">暂无授权</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>{u.enabled ? "已启用" : "已禁用"}</TableCell>
                      <TableCell className="text-right pr-4">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setUserEditor(u)}
                        >
                          编辑
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            setConfirm({
                              title: `轮换 ${u.id} 的令牌？旧令牌会立即失效。`,
                              run: async () => {
                                await mutate(
                                  `/api/admin/users/${u.id}/rotate`,
                                  {},
                                  "POST",
                                );
                              },
                            })
                          }
                        >
                          轮换令牌
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`删除用户 ${u.id}`}
                          onClick={() =>
                            setConfirm({
                              title: `删除用户 ${u.id}？`,
                              run: async () => {
                                await mutate(
                                  `/api/admin/users/${u.id}`,
                                  {},
                                  "DELETE",
                                );
                              },
                            })
                          }
                        >
                          <Trash2 size={14} />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          )}
          {page === "model" && (
            <ModelSettings
              state={state}
              token={token}
              busy={busy}
              action={action}
              mutate={mutate}
            />
          )}
          {page === "playground" && (
            <div className="two-col">
              <section className="panel p-6">
                <h2 className="section-title mb-2">虚拟命令</h2>
                <p className="subtle mb-5">
                  工具以当前管理员授权运行；这不是操作系统终端。
                </p>
                <Textarea
                  aria-label="虚拟命令"
                  className="mono min-h-32"
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                />
                <div className="flex flex-wrap gap-2 mt-3">
                  {["ls /mcp", "ls /os", "servers", "tools demo"].map((cmd) => (
                    <button
                      className="tag hover:text-indigo-600"
                      key={cmd}
                      onClick={() => setCommand(cmd)}
                    >
                      {cmd}
                    </button>
                  ))}
                </div>
                <Button
                  className="mt-5"
                  disabled={busy || !command.trim()}
                  onClick={execute}
                >
                  {busy ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Play size={15} />
                  )}
                  执行命令
                </Button>
              </section>
              <section className="panel p-6">
                <h2 className="section-title mb-4">执行结果</h2>
                {output !== null ? (
                  <pre className="result">
                    {JSON.stringify(output, null, 2)}
                  </pre>
                ) : (
                  <div className="empty">
                    <Terminal
                      size={28}
                      className="mx-auto mb-4 text-slate-300"
                    />
                    执行一次命令后，结果会显示在这里。
                  </div>
                )}
              </section>
            </div>
          )}
          {page === "playground" && (
            <section className="panel p-6 mt-6">
              <h2 className="section-title mb-2">让模型使用工具</h2>
              <p className="subtle mb-4">
                使用已保存的模型配置，最多8轮。任务和工具结果会发送给模型服务，可能产生费用。
              </p>
              <Textarea
                aria-label="模型任务"
                placeholder="例如：先发现工具，再计算2加3，并说明结果"
                value={agentTask}
                onChange={(e) => setAgentTask(e.target.value)}
              />
              <Button
                className="mt-4"
                disabled={busy || !agentTask.trim() || !state.model.model}
                onClick={() =>
                  action(async () => {
                    setAgentOutput(
                      await api(token, "/api/admin/agent", "POST", {
                        task: agentTask,
                      }),
                    );
                    setEvents(
                      (
                        await api<{ events: EventRow[] }>(
                          token,
                          "/api/admin/events",
                        )
                      ).events,
                    );
                  })
                }
              >
                <Sparkles size={15} />
                {busy ? "模型正在执行…" : "开始模型任务"}
              </Button>
              {!state.model.model && (
                <p className="subtle mt-2">先到「模型与凭证」保存配置。</p>
              )}
              {agentOutput !== null && (
                <pre className="result mt-4">
                  {JSON.stringify(agentOutput, null, 2)}
                </pre>
              )}
            </section>
          )}
          {page === "events" && (
            <section className="panel">
              <div className="panel-header">
                <h2 className="section-title">最近 100 条记录</h2>
                <span className="subtle">
                  最多保留 2,000 条 · 不保存原始命令参数
                </span>
              </div>
              <EventTable
                rows={events}
                onResult={(ref) =>
                  action(async () =>
                    setDetail(
                      await api(
                        token,
                        `/api/admin/result?ref=${encodeURIComponent(ref)}`,
                      ),
                    ),
                  )
                }
              />
            </section>
          )}
          {page === "operations" && (
            <Operations state={state} token={token} refresh={refresh} />
          )}
          <div className="footer-note">
            <span>MVS Console 0.3 · 统一管理 MCP 与原生命令</span>
            <span className="row">
              <ShieldCheck size={12} />
              默认拒绝 · 明确授权
            </span>
          </div>
        </main>
      </div>
      {editor !== undefined && (
        <ServerEditor
          server={editor}
          platform={state.platform}
          onClose={() => setEditor(undefined)}
          onSave={saveServer}
        />
      )}
      {userEditor !== undefined && (
        <UserEditor
          user={userEditor}
          servers={state.servers}
          onClose={() => setUserEditor(undefined)}
          onSave={async (id, value) => {
            await mutate(`/api/admin/users/${id}`, value);
          }}
        />
      )}
      <Dialog open={!!probe} onOpenChange={(v) => !v && setProbe(null)}>
        <DialogContent className="max-w-[700px] max-h-[85vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>{probe?.server.id} · 工具发现</DialogTitle>
            <DialogDescription>
              勾选需要开放的工具。连接测试只发现目录，不执行业务工具。
            </DialogDescription>
          </DialogHeader>
          {probe?.tools.map((t) => (
            <div className="flex gap-3 border-b py-4" key={t.name}>
              <Checkbox
                aria-label={`授权 ${t.name}`}
                checked={selected.includes(t.name)}
                onCheckedChange={(v) =>
                  setSelected(
                    v
                      ? [...selected, t.name]
                      : selected.filter((n) => n !== t.name),
                  )
                }
              />
              <div className="flex-1">
                <div className="font-mono text-sm font-medium">{t.name}</div>
                <p className="subtle mt-1">{t.description || "暂无说明"}</p>
                <details className="mt-2 text-xs text-slate-500">
                  <summary className="cursor-pointer">查看参数 Schema</summary>
                  <pre className="bg-slate-50 p-3 mt-2 rounded">
                    {JSON.stringify(t.input_schema, null, 2)}
                  </pre>
                </details>
              </div>
            </div>
          ))}
          <Button
            disabled={busy}
            onClick={() =>
              action(async () => {
                if (probe) {
                  await saveServer({
                    ...probe.server,
                    allowed_tools: selected,
                  });
                  setProbe(null);
                }
              })
            }
          >
            保存工具授权
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog open={!!issued} onOpenChange={(v) => !v && setIssued("")}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>请保存新的访问令牌</DialogTitle>
            <DialogDescription>
              令牌仅展示这一次。轮换管理员自身令牌后，需要用新令牌重新登录。
            </DialogDescription>
          </DialogHeader>
          <pre className="bg-slate-50 p-4 rounded break-all whitespace-pre-wrap text-xs">
            {issued}
          </pre>
          <Button onClick={() => navigator.clipboard.writeText(issued)}>
            <Copy size={14} />
            复制令牌
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog open={!!confirm} onOpenChange={(v) => !v && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认管理操作</DialogTitle>
            <DialogDescription>{confirm?.title}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 mt-3">
            <Button variant="outline" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await confirm?.run();
                  setConfirm(null);
                })
              }
            >
              确认执行
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={detail !== null}
        onOpenChange={(v) => !v && setDetail(null)}
      >
        <DialogContent className="max-w-[750px]">
          <DialogHeader>
            <DialogTitle>结果详情</DialogTitle>
            <DialogDescription>
              仅能读取属于当前主体的未过期结果。
            </DialogDescription>
          </DialogHeader>
          <pre className="result">{JSON.stringify(detail, null, 2)}</pre>
        </DialogContent>
      </Dialog>
      <Dialog open={setup} onOpenChange={setSetup}>
        <DialogContent className="max-w-[650px]">
          <DialogHeader>
            <DialogTitle>配置你的工作空间</DialogTitle>
            <DialogDescription>
              按照下面顺序完成配置。每一步都可以随时返回修改。
            </DialogDescription>
          </DialogHeader>
          <div className="steps">
            {[
              ["01", "配置模型", !!state.model.model, "model"],
              ["02", "连接工具", state.servers.length > 0, "servers"],
              [
                "03",
                "创建访问用户",
                state.users.some((u) => !u.roles.includes("admin")),
                "users",
              ],
            ].map(([num, title, done, target]) => (
              <button
                key={String(num)}
                className="step text-left"
                onClick={() => {
                  setSetup(false);
                  setPage(target as Page);
                }}
              >
                <div className="flex justify-between mb-3 text-indigo-500">
                  <span>{String(num)}</span>
                  {done ? <CheckCircle2 size={16} /> : <ArrowRight size={16} />}
                </div>
                <strong>{String(title)}</strong>
                <p className="subtle mt-1">
                  {done ? "已配置 · 可以修改" : "点击开始配置"}
                </p>
              </button>
            ))}
          </div>
          <div className="notice">
            先在工作台用 ls /mcp 或 ls /os 验证，再把普通用户令牌交给
            Agent。管理员令牌用于管理。
          </div>
          <Button
            onClick={() => {
              setSetup(false);
              setPage("playground");
            }}
          >
            前往工作台 <ArrowRight size={14} />
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
function EventTable({
  rows,
  onResult,
}: {
  rows: EventRow[];
  onResult: (ref: string) => void;
}) {
  return rows.length ? (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="pl-6">时间</TableHead>
          <TableHead>操作 / 请求</TableHead>
          <TableHead>主体</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>耗时</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((e) => (
          <TableRow key={e.id}>
            <TableCell className="pl-6 text-xs text-slate-500 py-4">
              {new Date(e.created * 1000).toLocaleString("zh-CN", {
                hour12: false,
              })}
            </TableCell>
            <TableCell className="text-xs font-mono">
              {e.action === "configuration_applied"
                ? "配置已应用"
                : e.action === "connection_test"
                  ? `连接测试 · ${e.server_id}`
                  : e.request_id?.slice(0, 14)}
            </TableCell>
            <TableCell className="text-xs text-slate-500">
              {e.principal_id ?? "管理员"}
            </TableCell>
            <TableCell>
              <Badge
                variant={e.status === "success" ? "secondary" : "destructive"}
              >
                {e.status === "success" ? "成功" : (e.error_code ?? e.status)}
              </Badge>
            </TableCell>
            <TableCell className="text-xs text-slate-400">
              {e.duration_ms != null ? `${e.duration_ms} ms` : "—"}
            </TableCell>
            <TableCell>
              {e.result_ref && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onResult(e.result_ref!)}
                >
                  结果 <ArrowRight size={12} />
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ) : (
    <div className="empty">
      暂无活动。连接一个服务或在工作台执行命令后，这里会出现记录。
    </div>
  );
}
function UserEditor({
  user,
  servers,
  onClose,
  onSave,
}: {
  user: User | null;
  servers: Server[];
  onClose: () => void;
  onSave: (id: string, value: Partial<User>) => Promise<void>;
}) {
  const [value, setValue] = useState<User>(
      user ?? {
        id: "",
        name: "",
        tenant_id: "default",
        roles: [],
        servers: [],
        enabled: true,
      },
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [rulesText, setRulesText] = useState(
    user?.rules ? JSON.stringify(user.rules, null, 2) : "",
  );
  const [refsText, setRefsText] = useState(
    JSON.stringify(user?.secret_refs ?? {}, null, 2),
  );
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{user ? "编辑用户" : "创建访问用户"}</DialogTitle>
          <DialogDescription>
            普通用户只能调用被授权服务中的白名单工具。
          </DialogDescription>
        </DialogHeader>
        {error && <div className="notice error">{error}</div>}
        {(["id", "name", "tenant_id"] as const).map((k, i) => (
          <div className="form-field" key={k}>
            <label htmlFor={`user-${k}`}>
              {["用户ID", "显示名称", "租户ID"][i]}
            </label>
            <Input
              id={`user-${k}`}
              disabled={k === "id" && !!user}
              value={value[k]}
              onChange={(e) => setValue({ ...value, [k]: e.target.value })}
            />
          </div>
        ))}
        <div className="form-field">
          <label>角色</label>
          <select
            aria-label="用户角色"
            className="form-select"
            value={value.roles.includes("admin") ? "admin" : "user"}
            onChange={(e) =>
              setValue({
                ...value,
                roles: e.target.value === "admin" ? ["admin"] : [],
              })
            }
          >
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </div>
        <label className="form-field">
          自定义角色（逗号分隔）
          <Input
            value={value.roles.filter((x) => x !== "admin").join(",")}
            onChange={(e) =>
              setValue({
                ...value,
                roles: [
                  ...(value.roles.includes("admin") ? ["admin"] : []),
                  ...e.target.value
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                ],
              })
            }
          />
        </label>
        <label className="form-field">
          每分钟请求上限
          <Input
            type="number"
            min={1}
            max={10000}
            value={value.rate_limit ?? 60}
            onChange={(e) =>
              setValue({ ...value, rate_limit: Number(e.target.value) })
            }
          />
        </label>
        <label className="text-xs font-semibold">授权服务</label>
        <div className="grid grid-cols-2 gap-3 py-3">
          {servers.map((s) => (
            <label key={s.id} className="row text-xs">
              <Checkbox
                checked={value.servers.includes(s.id)}
                onCheckedChange={(checked) =>
                  setValue({
                    ...value,
                    servers: checked
                      ? [...value.servers, s.id]
                      : value.servers.filter((x) => x !== s.id),
                  })
                }
              />
              {s.id}
            </label>
          ))}
        </div>
        <details className="mb-4">
          <summary className="text-xs cursor-pointer">
            高级用户规则与凭证映射
          </summary>
          <label className="form-field mt-3">
            用户工具/参数规则（留空沿用角色）
            <Textarea
              className="mono"
              value={rulesText}
              onChange={(e) => setRulesText(e.target.value)}
            />
          </label>
          <label className="form-field">
            凭证变量→托管凭证名
            <Textarea
              className="mono"
              value={refsText}
              onChange={(e) => setRefsText(e.target.value)}
            />
          </label>
        </details>
        <label className="row text-xs my-3">
          <Switch
            checked={value.enabled}
            onCheckedChange={(enabled) => setValue({ ...value, enabled })}
          />
          启用账户
        </label>
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const { id, ...body } = value;
              if (rulesText.trim()) body.rules = JSON.parse(rulesText);
              body.secret_refs = JSON.parse(refsText);
              await onSave(id, body);
              onClose();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在保存…" : "保存用户"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
function ModelSettings({
  state,
  token,
  busy,
  action,
  mutate,
}: {
  state: State;
  token: string;
  busy: boolean;
  action: (f: () => Promise<void>) => Promise<void>;
  mutate: (p: string, v: unknown, m?: string) => Promise<unknown>;
}) {
  const [model, setModel] = useState({
      base_url: state.model.base_url ?? "https://api.openai.com/v1",
      model: state.model.model ?? "",
      api_key_env: state.model.api_key_env ?? "MVS_SECRET_MODEL_KEY",
      reasoning_effort: state.model.reasoning_effort ?? "low",
    }),
    [secret, setSecret] = useState(""),
    [name, setName] = useState("MVS_SECRET_MODEL_KEY"),
    [result, setResult] = useState<unknown>(null);
  return (
    <div className="two-col">
      <section className="panel p-6">
        <div className="row mb-5">
          <div className="iconbox">
            <Sparkles size={20} />
          </div>
          <div>
            <h2 className="section-title">模型连接</h2>
            <p className="subtle mt-1">支持 OpenAI Responses 兼容接口</p>
          </div>
        </div>
        {(
          ["base_url", "model", "api_key_env", "reasoning_effort"] as const
        ).map((key, i) => (
          <div className="form-field" key={key}>
            <label htmlFor={`model-${key}`}>
              {["接口地址", "模型 ID", "凭证环境变量名", "推理强度"][i]}
            </label>
            <Input
              id={`model-${key}`}
              placeholder={
                key === "model" ? "填写账户实际可用的模型 ID" : undefined
              }
              value={model[key]}
              onChange={(e) => setModel({ ...model, [key]: e.target.value })}
            />
          </div>
        ))}
        <div className="flex gap-2">
          <Button
            disabled={busy}
            onClick={() =>
              action(async () => {
                await mutate("/api/admin/model", model);
              })
            }
          >
            保存模型配置
          </Button>
          <Button
            variant="outline"
            disabled={busy || !state.model.model}
            onClick={() =>
              action(async () =>
                setResult(await api(token, "/api/admin/model/test", "POST")),
              )
            }
          >
            <Zap size={14} />
            测试连接
          </Button>
        </div>
        <p className="subtle mt-3">
          测试会向已保存的模型发送一次简短请求，可能产生费用。
        </p>
        {result !== null && (
          <pre className="result mt-4">{JSON.stringify(result, null, 2)}</pre>
        )}
      </section>
      <section className="panel p-6">
        <div className="row mb-5">
          <div className="iconbox bg-amber-50 text-amber-600">
            <KeyRound size={20} />
          </div>
          <div>
            <h2 className="section-title">凭证管理</h2>
            <p className="subtle mt-1">只显示引用名称，不回显已有密钥</p>
          </div>
        </div>
        <div className="form-field">
          <label htmlFor="secret-name">凭证名称</label>
          <Input
            id="secret-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <small>使用 MVS_SECRET_ 前缀，供模型或 MCP 配置引用。</small>
        </div>
        <div className="form-field">
          <label htmlFor="secret-value">新的凭证值</label>
          <Input
            id="secret-value"
            type="password"
            autoComplete="off"
            placeholder="输入密钥，保存后不再展示"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
        </div>
        <Button
          variant="outline"
          disabled={busy || !secret}
          onClick={() =>
            action(async () => {
              await mutate(`/api/admin/secrets/${name}`, { secret });
              setSecret("");
            })
          }
        >
          保存凭证
        </Button>
        <div className="border-t mt-6 pt-4">
          <div className="subtle mb-3">已托管凭证</div>
          {state.secret_names.map((s) => (
            <div key={s} className="row justify-between py-2">
              <span className="text-xs font-mono">{s}</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                aria-label={`移除凭证 ${s}`}
                onClick={() =>
                  action(async () => {
                    await mutate(`/api/admin/secrets/${s}`, {});
                  })
                }
              >
                <Trash2 size={13} />
              </Button>
            </div>
          ))}
          {!state.secret_names.length && (
            <p className="subtle">暂无托管凭证，也可以直接使用进程环境变量。</p>
          )}
        </div>
        <p className="text-[11px] text-slate-400 leading-5 mt-5">
          本机凭证保存在当前用户私有的数据目录中；这不是云端密钥库。请限制该目录访问权限。
        </p>
      </section>
    </div>
  );
}
