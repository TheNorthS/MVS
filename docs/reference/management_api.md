# 安装实例与管理接口

当前支持 `/api/admin/history`、历史restore、`roles/{role}`、审批列表/参数/decide、
templates/install、OAuth配置/start/callback/revoke。用户字段新增rules、secret_refs、rate_limit。
模型新增protocol与fallbacks。完整行为与限制见[生产能力说明](../guides/production_features.md)。
当前版本为0.0.1；运行时保留有效会话并复用未变化服务。

`mvs serve` 启动新的管理控制面，同时保留原 `/api/v1/*` 工具执行接口。旧
`examples/deploy_api.py` 是静态YAML入口，没有这些管理接口。两个入口不能共享运行端口。

管理接口统一使用 `Authorization: Bearer <管理员令牌>`。普通用户返回403，无效令牌返回401。
写请求需要 `{"revision": 当前版本号, "value": {...}}`；删除/轮换的value可省略。
状态接口不返回令牌摘要、令牌明文或托管凭证值。

| 接口                               | 作用                                                |
| ---------------------------------- | --------------------------------------------------- |
| GET /api/admin/state               | 当前配置、版本、当前用户ID、平台、服务健康          |
| PUT /api/admin/servers/{id}        | 校验并新增/替换服务，ID与请求体一致                 |
| DELETE /api/admin/servers/{id}     | 删除服务并移除关联授权                              |
| POST /api/admin/servers/{id}/probe | 实际连接并发现工具；不执行业务工具                  |
| PUT /api/admin/users/{id}          | 新增或修改用户；新增返回一次 issued_token           |
| POST /api/admin/users/{id}/rotate  | 轮换令牌，旧令牌失效，返回一次 issued_token         |
| DELETE /api/admin/users/{id}       | 删除用户，禁止删除最后一个启用管理员                |
| PUT /api/admin/model               | 保存模型base_url/model/api_key_env/reasoning_effort |
| PUT /api/admin/secrets/{name}      | 写入value.secret；省略secret表示删除                |
| POST /api/admin/model/test         | 对已保存模型发出简短请求，可能计费                  |
| POST /api/admin/agent              | body为task字符串对象；真实模型通过既有API调用工具   |
| GET /api/admin/events              | 最近100条事件；数据库最多保留2000条                 |
| GET /api/admin/result?ref=...      | 查看当前主体自己的未过期结果；大结果仍需分页        |

新用户默认没有服务授权；工具仍受各服务的allowed_tools约束，还可通过用户/角色规则限定
工具、参数、资源和提示词。新服务自动加入管理员可访问列表，普通用户必须单独授权。
启停、密钥、模型配置等修改均走配置代际切换，仍有效的会话与当前目录会保留。

变更流程：校验新配置→获取运行时切换锁→再次检查管理员身份和版本→构建新实例→事务写入
SQLite或共享PostgreSQL→发布新运行实例→关闭旧实例。版本冲突返回409，校验失败保留旧状态。
下游连接失败会标记offline，不等于配置事务失败。普通请求并发执行，切换等待在途请求完成；
共享控制面在执行前同步配置版本，同机双进程功能已通过验收。

实例锁阻止同一目录的多个管理进程。命令行离线配置导入和令牌恢复使用同一锁。
服务数据与调用事件默认保存在本机SQLite，可切换共享PostgreSQL；托管凭证采用Fernet加密，见安装说明。
浏览器只在内存保存管理令牌，要求同源请求，响应禁用缓存和被iframe嵌入。

前端组件由shadcn/ui官方new-york注册表导入，来源见web/shadcn-sources.json，MIT许可随包
保存在mvs/web/licenses/shadcn-ui.txt。组件本身是项目内源码，不依赖远程CDN运行。
