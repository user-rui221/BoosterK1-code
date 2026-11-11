#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/../.."
source /opt/ros/humble/setup.bash
source install/setup.bash
exec python3 tools/vision_viewer/viewer.py "$@"
