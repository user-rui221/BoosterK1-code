#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    echo "请先运行本目录中的 ./setup_linux.sh 安装依赖。" >&2
    exit 1
fi
if [[ -d linux-libs ]]; then
    export LD_LIBRARY_PATH="$PWD/linux-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec .venv/bin/python desktop.py "$@"
