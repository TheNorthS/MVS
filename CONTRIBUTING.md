# 参与开发

欢迎在[TheNorthS/MVS](https://github.com/TheNorthS/MVS)提交问题与改进。
使用Python 3.12+、uv和Node.js 22；前端位于`web/`，Python源码位于`src/mvs/`。

```bash
uv sync --locked --all-extras
uv run python scripts/project_metadata.py
uv run python scripts/check_repository.py
uv run ruff check .
uv run mypy
uv run pytest -q
```

前端变更还需运行`npm --prefix web ci`与`npm --prefix web run build`。
真实外部服务测试见[Docker验收教程](docs/guides/docker_acceptance.md)，真实模型实验会计费，
不属于普通测试。不要提交API密钥、运行数据库、实例文件或用户数据。

当前版本固定为0.0.1；修改功能时不要自行递增版本。新增MCP调用保持在适配层，复用统一权限、
审计和结果约束，提供与实际行为对应的测试与中文文档。项目使用[MIT许可证](LICENSE)，
贡献时保留第三方许可声明。

[目录与版本约定](docs/development/repository_layout.md) · [发布流程](docs/development/publishing.md)
