# 维护脚本

这些脚本均从仓库根目录调用。保留平铺的稳定入口，方便安装包和CI引用。

| 脚本                        | 用途                                             |
| --------------------------- | ------------------------------------------------ |
| `project_metadata.py`       | 检查Python、前端及两个锁文件的版本一致性         |
| `check_repository.py`       | 检查Git待提交文件范围及疑似凭据，只显示位置      |
| `check_distributions.py`    | 检查wheel/sdist元数据、页面、许可及文件范围      |
| `build_release.py`          | 构建前端、明确版本wheel与标准安装ZIP             |
| `release_bundle.py`         | 打包辅助模块，统一PowerShell UTF-8 BOM与文件哈希 |
| `install.ps1`、`install.sh` | 最终用户安装标准wheel并初始化实例                |
| `installer_gui.py`          | 基于Tk的图形安装入口                             |
| `full_offline_bundle.py`    | 打包当前平台Python、uv及核心/控制台依赖          |
| `offline_install.py`        | 完整离线包内部安装器，校验manifest后安装         |
| `build_offline.py`          | 只下载依赖wheel，目标机器仍需Python与uv          |
| `test_docker.py`            | 启动独立临时服务并进行真实集成验收               |
| `check_licenses.py`         | 检查生成的依赖许可证报告                         |

临时调试代码放在不提交的`.tools/`，不要混入稳定入口。版本保持0.0.1，构建不自动递增。
发布产物在`dist/release/0.0.1/`，源码从本仓库直接提交并推送，见[发布指南](../docs/development/publishing.md)。
