"""正式分发必须携带后台资源；开发用editable安装可以先准备Python环境。"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name == "wheel" and version == "editable":
            return
        web = Path(self.root) / "src/mvs/web"
        required = [web / "index.html", web / "licenses/shadcn-ui.txt"]
        if not all(p.is_file() for p in required) or not list((web / "assets").glob("*.js")):
            raise ValueError(
                "正式构建缺少管理后台资源。请先运行npm --prefix web ci和"
                "npm --prefix web run build，或使用python scripts/build_release.py。"
            )
