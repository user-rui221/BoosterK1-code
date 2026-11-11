#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Newer Qt needs this small X11 library; keep a private copy when it is absent.
if python3 -c 'import ctypes; ctypes.CDLL("libxcb-cursor.so.0")' 2>/dev/null; then
    exit 0
fi
if [[ -f linux-libs/libxcb-cursor.so.0 ]]; then
    exit 0
fi
if ! command -v apt-get >/dev/null || ! command -v dpkg-deb >/dev/null; then
    echo "请使用发行版包管理器安装 libxcb-cursor（Ubuntu 包名 libxcb-cursor0）。" >&2
    exit 1
fi
mkdir -p build/system-libs linux-libs
(
    cd build/system-libs
    apt-get download libxcb-cursor0
    for package in libxcb-cursor0_*.deb; do
        dpkg-deb -x "$package" extracted
    done
)
library=$(find build/system-libs/extracted -type f -name 'libxcb-cursor.so.*' -print -quit)
[[ -n "$library" ]]
cp "$library" linux-libs/libxcb-cursor.so.0
cp build/system-libs/extracted/usr/share/doc/libxcb-cursor0/copyright linux-libs/COPYRIGHT-libxcb-cursor
