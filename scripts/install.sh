#!/bin/sh
# 用户解压发布包后执行；不需要Node，不修改系统服务，不覆盖已有实例配置。
set -eu
MVS_RELEASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MVS_PACKAGE=${1:-}
if [ -z "$MVS_PACKAGE" ]; then
  for candidate in "$MVS_RELEASE_DIR"/*.whl "$MVS_RELEASE_DIR"/dist/*.whl; do
    if [ -f "$candidate" ]; then MVS_PACKAGE=$candidate; break; fi
  done
fi
if [ -z "$MVS_PACKAGE" ]; then
  echo '没有找到发布wheel。用法：sh scripts/install.sh /路径/mcp_virtual_shell-0.0.1-py3-none-any.whl' >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  MVS_UV_INSTALL=$(mktemp)
  trap 'rm -f "$MVS_UV_INSTALL"' EXIT HUP INT TERM
  curl -LsSf https://astral.sh/uv/0.13.8/install.sh -o "$MVS_UV_INSTALL"
  sh "$MVS_UV_INSTALL"
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi
uv tool install --python 3.12 --force "${MVS_PACKAGE}[console]"
MVS_BIN_DIR=$(uv tool dir --bin)
"$MVS_BIN_DIR/mvs" init
echo "安装完成。运行 $MVS_BIN_DIR/mvs token show 查看令牌，然后运行 $MVS_BIN_DIR/mvs serve --open。"
