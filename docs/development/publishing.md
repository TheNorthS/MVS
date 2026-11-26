# GitHub与PyPI发布（0.0.1）

源码仓库为[TheNorthS/MVS](https://github.com/TheNorthS/MVS)，项目使用MIT许可证。
Python包名为`mcp-virtual-shell`，命令为`mvs`、`mvs-agent`、`mvs-benchmark`。
当前版本固定为 **0.0.1**，构建和工作流不会自动递增版本。

**0.0.1已于2026-11-26发布到[PyPI](https://pypi.org/project/mcp-virtual-shell/0.0.1/)。**
本次从提交`8983edc`构建的wheel与sdist，经用户授权用仅传给上传进程的token发布；未将token
写入仓库或GitHub Secret。此前可信发布返回`invalid-publisher`，所以下文的PyPI可信发布者
仍需配置后才能用于后续自动发布。已上传的0.0.1文件不能覆盖。

## 1. 提交哪些文件

提交源码、前端源码、测试、示例配置、文档、许可证、锁文件与已保留的研究记录。
`.gitignore`排除`.tools/`、`.venv/`、`.mvs/`、缓存、数据库、凭证、备份、`dist/`和前端生成目录。
实验JSON/XML使用`.gitattributes`保留原始字节，避免Git换行转换破坏记录哈希。
不要使用`git add -f`绕过这些规则。检查命令只报告位置，不输出疑似密钥正文：

```bash
uv sync --locked --all-extras
uv run python scripts/project_metadata.py
uv run python scripts/check_repository.py
git status --short
git diff --cached --stat
```

元数据中的仓库、文档、问题反馈地址均指向`https://github.com/TheNorthS/MVS`。
将本地源码直接提交到仓库，不生成GitHub源码ZIP：

```bash
git add .
git commit -m "Prepare MVS 0.0.1 release"
git push -u origin main
```

这些命令适用于已配置origin、当前分支为main且提交内容已核对的工作区。
普通推送触发检查工作流，不会发布到PyPI或创建GitHub Release。

## 2. 构建分发物

维护者需要Python 3.12+、uv、Node.js 22和npm，最终用户运行wheel不需要Node。

```bash
uv run python scripts/build_release.py
uvx twine check --strict dist/release/0.0.1/pypi/*
```

已安装前端依赖时可加`--skip-install`；仍会重新构建页面。默认输出结构：

```text
dist/release/0.0.1/
├── pypi/
│   ├── mcp_virtual_shell-0.0.1-py3-none-any.whl
│   └── mcp_virtual_shell-0.0.1.tar.gz
├── installers/
│   └── mcp_virtual_shell-0.0.1-installer.zip
└── SHA256SUMS.json
```

`pypi/`只用于wheel和sdist，安装ZIP不可上传PyPI。uv可能额外生成隐藏的`.gitignore`，
它不是分发物。旧的`dist/`根目录和归档文件不参与这次发布。

构建入口检查前后端及锁文件版本、Git待提交内容、wheel/sdist名称和MIT元数据、页面资源、
许可文件及文件范围。wheel从sdist重建，sdist自身携带已构建的页面，用户从sdist安装也无需Node。
直接从干净Git源码构建正式包前要先构建前端；editable开发安装允许尚未生成页面。

PyPI使用`docs/PYPI.md`作为介绍，链接为完整GitHub URL，避免相对图片或Mermaid在PyPI失效。
GitHub首页继续使用详细的`README.md`。依赖版本保持锁文件现有值，不因发布整理自动升级。

## 3. 配置PyPI可信发布

在PyPI或TestPyPI中确认`mcp-virtual-shell`项目名称可用且归你的账户管理；两者账户独立。
在对应项目或Pending Publisher中配置GitHub可信发布者：

| 字段        | PyPI          | TestPyPI      |
| ----------- | ------------- | ------------- |
| Owner       | `TheNorthS`   | `TheNorthS`   |
| Repository  | `MVS`         | `MVS`         |
| Workflow    | `release.yml` | `release.yml` |
| Environment | `pypi`        | `testpypi`    |

在GitHub仓库Settings → Environments建立对应环境，可按维护习惯设置发布审核人。
发布作业使用OIDC短期身份，不需要把长期PyPI token写入仓库。
配置方法以[PyPI可信发布文档](https://docs.pypi.org/trusted-publishers/using-a-publisher/)为准。

## 4. 从本仓库运行发布工作流

打开GitHub → Actions → `release` → Run workflow，选择main及目标：

| 参数                             | 行为                                                         |
| -------------------------------- | ------------------------------------------------------------ |
| `destination=build-only`（默认） | 检查、构建并上传工作流产物，不上传包索引                     |
| `destination=testpypi`           | 构建成功后上传TestPyPI                                       |
| `destination=pypi`               | 构建成功后上传PyPI                                           |
| `github_draft=true`              | 额外创建`v0.0.1`草稿Release，附wheel、sdist、安装ZIP和哈希表 |

发布作业只下载本次构建产物；构建、GitHub写入与PyPI身份权限分开配置。
重复运行不会静默忽略已有同版本文件。0.0.1保持固定，但PyPI已发布文件名不能覆盖；
发布前应完成验证，后续更改需由维护者明确决定新版本，不能假装同一版本可反复覆盖。

发布后，在全新环境验证安装：

```bash
uv tool install --python 3.12 'mcp-virtual-shell[console]==0.0.1'
mvs init
mvs doctor
mvs serve --open
```

TestPyPI不一定具备项目全部依赖，测试时先从正式PyPI安装依赖，再用`--no-deps`安装
TestPyPI下载的项目wheel，避免混用索引误装同名依赖。

本地构建和检查通过不等于远程CI或PyPI发布已成功，需查看对应工作流及包索引的实际结果。
