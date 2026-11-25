import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, type State } from "@/lib/api";

type Props = { state: State; token: string; refresh: () => Promise<unknown> };
export function Operations({ state, token, refresh }: Props) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [approvals, setApprovals] = useState<Record<string, unknown>[]>([]),
    [history, setHistory] = useState<{ revision: number; created: number }[]>(
      [],
    ),
    [detail, setDetail] = useState<unknown>(null);
  const [tab, setTab] = useState("approvals"),
    [role, setRole] = useState("reader"),
    [rules, setRules] = useState(
      '{"demo":{"tools":["add"],"arguments":{"add":{"type":"object","properties":{"a":{"maximum":10}}}}}}',
    );
  const [template, setTemplate] = useState("git"),
    [server, setServer] = useState("gitrepo"),
    [repo, setRepo] = useState(""),
    [oauthName, setOauthName] = useState("provider"),
    [oauth, setOauth] = useState(
      '{"authorization_url":"https://id.example/authorize","token_url":"https://id.example/token","client_id":"mvs","redirect_uri":"http://localhost:8080/api/oauth/callback","scope":"read"}',
    ),
    [model, setModel] = useState(JSON.stringify(state.model, null, 2));
  async function load() {
    setApprovals(
      (
        await api<{ approvals: Record<string, unknown>[] }>(
          token,
          "/api/admin/approvals",
        )
      ).approvals,
    );
    setHistory(
      (
        await api<{ history: { revision: number; created: number }[] }>(
          token,
          "/api/admin/history",
        )
      ).history,
    );
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      setDetail(await fn());
      await refresh();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel p-6">
      <h2 className="section-title mb-4">治理与运维</h2>
      <div className="flex flex-wrap gap-2 mb-6">
        {[
          ["approvals", "审批"],
          ["history", "配置回滚"],
          ["roles", "角色规则"],
          ["templates", "MCP安装"],
          ["oauth", "OAuth"],
          ["models", "多模型路由"],
        ].map(([id, label]) => (
          <Button
            key={id}
            variant={tab === id ? "default" : "outline"}
            onClick={() => setTab(id)}
          >
            {label}
          </Button>
        ))}
      </div>
      {error && (
        <div role="alert" className="notice error">
          {error}
        </div>
      )}
      {tab === "approvals" && (
        <>
          {!approvals.length && (
            <div className="empty">
              暂无审批。配置 approval_tools 的调用会自动生成审批。
            </div>
          )}
          {approvals.map((a) => (
            <div key={String(a.id)} className="border-b py-4">
              <div className="flex justify-between">
                <strong>
                  {String(a.server)} / {String(a.tool)}
                </strong>
                <span>{String(a.state)}</span>
              </div>
              <p className="subtle mt-2">
                申请人 {String(a.owner)} · 租户 {String(a.tenant)} · 有效期至{" "}
                {new Date(Number(a.expires) * 1000).toLocaleString()}
              </p>
              <div className="flex gap-2 mt-3">
                <Button
                  variant="outline"
                  onClick={() =>
                    run(() => api(token, `/api/admin/approvals/${a.id}`))
                  }
                >
                  查看参数
                </Button>
                {a.state === "pending" &&
                  [true, false].map((approve) => (
                    <Button
                      key={String(approve)}
                      disabled={busy}
                      variant={approve ? "default" : "destructive"}
                      onClick={() =>
                        run(() =>
                          api(
                            token,
                            `/api/admin/approvals/${a.id}/decide`,
                            "POST",
                            { revision: state.revision, value: { approve } },
                          ),
                        )
                      }
                    >
                      {approve ? "批准一次" : "拒绝"}
                    </Button>
                  ))}
              </div>
              <code className="text-xs">{String(a.id)}</code>
            </div>
          ))}
          <p className="subtle mt-4">
            申请方重交原命令并携带approval_id；参数、主体、工具版本必须一致，批准仅可消费一次。
          </p>
        </>
      )}
      {tab === "history" && (
        <>
          {history.map((h) => (
            <div
              key={h.revision}
              className="flex items-center justify-between border-b py-3"
            >
              <span>
                版本 {h.revision} ·{" "}
                {new Date(h.created * 1000).toLocaleString()}
              </span>
              <Button
                disabled={busy}
                variant="outline"
                onClick={() => {
                  if (confirm("回滚服务与模型配置？当前身份令牌不会回滚。"))
                    void run(() =>
                      api(
                        token,
                        `/api/admin/history/${h.revision}/restore`,
                        "POST",
                        { revision: state.revision },
                      ),
                    );
                }}
              >
                恢复此版本
              </Button>
            </div>
          ))}
        </>
      )}
      {tab === "roles" && (
        <>
          <label className="form-field">
            角色名
            <Input value={role} onChange={(e) => setRole(e.target.value)} />
          </label>
          <label className="form-field">
            服务→工具/参数规则
            <Textarea
              className="mono min-h-48"
              value={rules}
              onChange={(e) => setRules(e.target.value)}
            />
          </label>
          <Button
            disabled={busy}
            onClick={() =>
              run(() =>
                api(token, `/api/admin/roles/${role}`, "PUT", {
                  revision: state.revision,
                  value: JSON.parse(rules),
                }),
              )
            }
          >
            保存角色
          </Button>
          <p className="subtle mt-3">
            用户的rules或roles通过管理API配置；规则与服务白名单相交，不能越过服务权限。
          </p>
        </>
      )}
      {tab === "templates" && (
        <>
          <label className="form-field">
            可信模板
            <select
              className="form-select"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
            >
              <option value="git">Git · 固定2026.11.11</option>
              <option value="fetch">Fetch · 固定2026.11.11</option>
            </select>
          </label>
          <label className="form-field">
            服务ID
            <Input value={server} onChange={(e) => setServer(e.target.value)} />
          </label>
          {template === "git" && (
            <label className="form-field">
              仓库绝对路径
              <Input value={repo} onChange={(e) => setRepo(e.target.value)} />
            </label>
          )}
          <Button
            disabled={busy}
            onClick={() =>
              run(() =>
                api(token, `/api/admin/templates/${template}/install`, "POST", {
                  revision: state.revision,
                  value: { server_id: server, repository: repo },
                }),
              )
            }
          >
            {busy ? "安装中…" : "安装隔离环境并注册"}
          </Button>
        </>
      )}
      {tab === "oauth" && (
        <>
          <label className="form-field">
            提供方名称
            <Input
              value={oauthName}
              onChange={(e) => setOauthName(e.target.value)}
            />
          </label>
          <Textarea
            className="mono min-h-48"
            value={oauth}
            onChange={(e) => setOauth(e.target.value)}
          />
          <div className="flex gap-2 mt-4">
            <Button
              onClick={() =>
                run(() =>
                  api(token, `/api/admin/oauth/${oauthName}`, "PUT", {
                    revision: state.revision,
                    value: JSON.parse(oauth),
                  }),
                )
              }
            >
              保存OAuth配置
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                run(async () => {
                  const result = await api<{ url: string }>(
                    token,
                    `/api/oauth/${oauthName}/start`,
                    "POST",
                  );
                  window.open(result.url, "_blank", "noopener");
                  return { status: "已打开授权页面" };
                })
              }
            >
              授权当前用户
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                run(() => api(token, `/api/oauth/${oauthName}/revoke`, "POST"))
              }
            >
              撤销授权
            </Button>
          </div>
          <p className="subtle mt-3">
            MCP的auth_ref填写oauth:提供方名称。每位用户分别授权，支持PKCE、续期和撤销。
          </p>
        </>
      )}
      {tab === "models" && (
        <>
          <p className="subtle mb-4">
            protocol支持responses、chat_completions、anthropic；fallbacks为最多3个备用配置。接口失败才切换，不重放工具调用。
          </p>
          <Textarea
            className="mono min-h-64"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <Button
            className="mt-4"
            onClick={() =>
              run(() =>
                api(token, "/api/admin/model", "PUT", {
                  revision: state.revision,
                  value: JSON.parse(model),
                }),
              )
            }
          >
            保存路由配置
          </Button>
        </>
      )}
      {detail !== null && (
        <pre className="result mt-6">{JSON.stringify(detail, null, 2)}</pre>
      )}
    </section>
  );
}
