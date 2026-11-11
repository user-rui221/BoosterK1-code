#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
./prepare_linux_libs.sh
extra_binaries=()
if [[ -f linux-libs/libxcb-cursor.so.0 ]]; then
    extra_binaries+=(--add-binary "$PWD/linux-libs/libxcb-cursor.so.0:.")
    export LD_LIBRARY_PATH="$PWD/linux-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
env -u PYTHONPATH .venv/bin/python -m PyInstaller "${extra_binaries[@]}" --noconfirm --clean --windowed --onedir \
    --name RefereeBox --distpath dist --workpath build --specpath build desktop.py
cp DESKTOP_README.md dist/RefereeBox/README.md
cp LICENSE dist/RefereeBox/LICENSE
cp -r third_party_licenses dist/RefereeBox/
if [[ -f linux-libs/COPYRIGHT-libxcb-cursor ]]; then
    cp linux-libs/COPYRIGHT-libxcb-cursor dist/RefereeBox/
fi
.venv/bin/python - <<'LICENSES'
from importlib.metadata import distribution
from pathlib import Path
import shutil
for package in ('PySide6-Essentials', 'shiboken6', 'pyinstaller'):
    dist = distribution(package)
    target = Path('dist/RefereeBox/third_party_licenses') / package
    target.mkdir(parents=True, exist_ok=True)
    (target / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
    for file in dist.files or []:
        if 'license' in str(file).lower() or 'copying' in str(file).lower():
            source = dist.locate_file(file)
            if source.is_file():
                destination = target / str(file)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
LICENSES
tar -czf dist/RefereeBox-source.tar.gz --transform='s,^,RefereeBox-source/,' \
    desktop.py desktop_core.py referee_box.py test_desktop.py test_referee_box.py test_reset.py \
    requirements-desktop.txt requirements-build.txt setup_linux.sh run_desktop.sh \
    build_linux.sh prepare_linux_libs.sh DESKTOP_README.md README.md LICENSE third_party_licenses
tar -czf "dist/RefereeBox-linux-$(uname -m).tar.gz" -C dist RefereeBox
echo "完成：dist/RefereeBox-linux-$(uname -m).tar.gz"
