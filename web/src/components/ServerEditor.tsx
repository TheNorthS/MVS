import { useState } from "react";
import {
  Plus,
  Terminal,
  Globe,
  Server as ServerIcon,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import type { Server, Native } from "@/lib/api";

const parseLines = (s: string) =>
  s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
export function ServerEditor({
  server,
  platform,
  onClose,
  onSave,
}: {
  server: Server | null;
  platform: string;
  onClose: () => void;
  onSave: (s: Server) => Promise<void>;
}) {
  const [value, setValue] = useState<Server>(
    server ?? {
      id: "",
      transport: "stdio",
      enabled: true,
      command: "",
      args: [],
      allowed_tools: [],
      max_concurrency: 2,
      call_timeout_seconds: 15,
    },
  );
  const [args, setArgs] = useState((server?.args ?? []).join("\n"));
  const [allow, setAllow] = useState((server?.allowed_tools ?? []).join(", "));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [raw, setRaw] = useState(JSON.stringify(server ?? value, null, 2));
  const update = (key: string, val: unknown) =>
    setValue((v) => ({ ...v, [key]: val }));
  const [native, setNative] = useState({
    name: server?.native_commands?.[0]?.name ?? "hostname",
    description: server?.native_commands?.[0]?.description ?? "读取本机主机名",
    executable:
      server?.native_commands?.[0]?.implementations?.[platform]?.executable ??
      (platform === "win32"
        ? "C:\\Windows\\System32\\hostname.exe"
        : "/bin/hostname"),
    cwd:
      server?.native_commands?.[0]?.implementations?.[platform]?.cwd ??
      (platform === "win32" ? "C:\\Windows" : "/tmp"),
    argv: JSON.stringify(
      server?.native_commands?.[0]?.implementations?.[platform]?.argv ?? [],
    ),
    schema: JSON.stringify(
      server?.native_commands?.[0]?.input_schema ?? {
        type: "object",
        additionalProperties: false,
      },
      null,
      2,
    ),
  });
  function formValue(): Server {
    const result: Server = {
      ...value,
      allowed_tools: allow
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    };
    if (value.transport === "stdio") {
      result.command = value.command;
      result.args = parseLines(args);
      delete result.url;
      delete result.native_commands;
    }
    if (value.transport === "streamable_http") {
      result.http_allowed_hosts = [new URL(value.url ?? "").hostname];
      delete result.command;
      delete result.args;
      delete result.native_commands;
    }
    if (value.transport === "native") {
      delete result.command;
      delete result.args;
      delete result.url;
      delete result.auth_ref;
      const first: Native = {
        ...(server?.native_commands?.[0] ?? {}),
        name: native.name,
        description: native.description,
        input_schema: JSON.parse(native.schema),
        implementations: {
          ...(server?.native_commands?.[0]?.implementations ?? {}),
          [platform]: {
            executable: native.executable,
            cwd: native.cwd,
            argv: JSON.parse(native.argv),
            encoding: "utf-8",
          },
        },
      };
      result.native_commands = [
        first,
        ...(server?.native_commands?.slice(1) ?? []),
      ];
    }
    return result;
  }
  async function save() {
    setError("");
    setBusy(true);
    try {
      await onSave(advanced ? JSON.parse(raw) : formValue());
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-[700px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{server ? "编辑服务配置" : "添加服务"}</DialogTitle>
          <DialogDescription>
            注册 MCP 服务或原生命令。保存后应用配置，已有会话需要重新创建。
          </DialogDescription>
        </DialogHeader>
        {error && (
          <div role="alert" className="notice error">
            {error}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              try {
                if (!advanced) {
                  setRaw(JSON.stringify(formValue(), null, 2));
                  setAdvanced(true);
                } else {
                  setError("高级配置请直接保存；关闭窗口可放弃更改。");
                }
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <ChevronDown size={14} /> {advanced ? "高级模式" : "高级 JSON"}
          </Button>
        </div>
        {advanced ? (
          <Textarea
            aria-label="完整服务配置"
            className="mono min-h-80"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
          />
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {[
                ["stdio", "本地 MCP", ServerIcon],
                ["streamable_http", "远程 MCP", Globe],
                ["native", "原生命令", Terminal],
              ].map(([type, label, Icon]) => (
                <button
                  key={String(type)}
                  type="button"
                  onClick={() => update("transport", type)}
                  className={`rounded-lg border p-3 text-left ${value.transport === type ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "text-slate-500"}`}
                >
                  <Icon size={18} className="mb-2" />
                  {String(label)}
                </button>
              ))}
            </div>
            <div className="form-field">
              <label htmlFor="server-id">服务 ID</label>
              <Input
                id="server-id"
                placeholder="例如 github、database、host"
                disabled={!!server}
                value={value.id}
                onChange={(e) => update("id", e.target.value)}
              />
              <small>小写字母开头，只包含字母、数字、横线或下划线。</small>
            </div>
            {value.transport === "stdio" && (
              <>
                <div className="form-field">
                  <label htmlFor="executable">启动程序</label>
                  <Input
                    id="executable"
                    placeholder="python 或程序的绝对路径"
                    value={value.command ?? ""}
                    onChange={(e) => update("command", e.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="args">启动参数 · 每行一个</label>
                  <Textarea
                    id="args"
                    value={args}
                    onChange={(e) => setArgs(e.target.value)}
                    placeholder={
                      "-m\nmcp_server_git\n--repository\n/srv/project"
                    }
                  />
                </div>
              </>
            )}
            {value.transport === "streamable_http" && (
              <>
                <div className="form-field">
                  <label htmlFor="endpoint">MCP 端点</label>
                  <Input
                    id="endpoint"
                    placeholder="https://mcp.example.com/mcp"
                    value={value.url ?? ""}
                    onChange={(e) => update("url", e.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="auth-env">凭证环境变量（可选）</label>
                  <Input
                    id="auth-env"
                    placeholder="MVS_SECRET_REMOTE_TOKEN"
                    value={value.auth_ref ?? ""}
                    onChange={(e) => update("auth_ref", e.target.value || null)}
                  />
                  <small>在「模型与凭证」页写入凭证；这里只保存引用。</small>
                </div>
              </>
            )}
            {value.transport === "native" && (
              <div className="native-editor">
                <div className="row mb-4">
                  <Terminal size={16} />
                  <strong>原生命令 · {platform}</strong>
                </div>
                {(["name", "description", "executable", "cwd"] as const).map(
                  (key, i) => (
                    <div className="form-field" key={key}>
                      <label htmlFor={`native-${key}`}>
                        {["命令名", "说明", "程序绝对路径", "固定工作目录"][i]}
                      </label>
                      <Input
                        id={`native-${key}`}
                        value={native[key]}
                        onChange={(e) =>
                          setNative({ ...native, [key]: e.target.value })
                        }
                      />
                    </div>
                  ),
                )}
                <div className="form-field">
                  <label htmlFor="native-argv">参数绑定（JSON 数组）</label>
                  <Textarea
                    id="native-argv"
                    className="mono"
                    value={native.argv}
                    onChange={(e) =>
                      setNative({ ...native, argv: e.target.value })
                    }
                  />
                  <small>
                    例如 ["--", &#123;"param":"path"&#125;]。不执行任意 Shell
                    文本。
                  </small>
                </div>
                <div className="form-field">
                  <label htmlFor="native-schema">输入 JSON Schema</label>
                  <Textarea
                    id="native-schema"
                    className="mono min-h-28"
                    value={native.schema}
                    onChange={(e) =>
                      setNative({ ...native, schema: e.target.value })
                    }
                  />
                  <small>多命令、路径范围和其他平台实现请使用高级 JSON。</small>
                </div>
              </div>
            )}
            <div className="form-field">
              <label htmlFor="allowlist">允许调用的工具 · 逗号分隔</label>
              <Input
                id="allowlist"
                placeholder="留空表示暂不允许调用，连接后可发现工具"
                value={allow}
                onChange={(e) => setAllow(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="form-field">
                <label htmlFor="concurrency">最大并发</label>
                <Input
                  id="concurrency"
                  type="number"
                  min={1}
                  value={value.max_concurrency ?? 2}
                  onChange={(e) =>
                    update("max_concurrency", Number(e.target.value))
                  }
                />
              </div>
              <div className="form-field">
                <label htmlFor="timeout">调用超时（秒）</label>
                <Input
                  id="timeout"
                  type="number"
                  min={1}
                  value={value.call_timeout_seconds ?? 15}
                  onChange={(e) =>
                    update("call_timeout_seconds", Number(e.target.value))
                  }
                />
              </div>
            </div>
            <div className="row justify-between mb-4">
              <span>启用此服务</span>
              <Switch
                checked={value.enabled !== false}
                onCheckedChange={(checked) => update("enabled", checked)}
              />
            </div>
          </>
        )}
        <div className="flex justify-end gap-2 border-t pt-4">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button disabled={busy} onClick={save}>
            <Plus size={15} />
            {busy ? "正在校验并应用…" : "保存并应用"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
