#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if command -v uv >/dev/null 2>&1; then
    if [[ ! -x .venv/bin/python ]]; then
        uv venv .venv
    fi
    uv pip install --python .venv/bin/python -r requirements-build.txt
else
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-build.txt
fi
./prepare_linux_libs.sh
echo "安装完成。运行 ./run_desktop.sh"
