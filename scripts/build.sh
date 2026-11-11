#!/bin/bash

cd `dirname $0`
cd ..

source /opt/ros/humble/setup.bash

export PYTHONWARNINGS="ignore::DeprecationWarning,ignore::UserWarning,ignore::FutureWarning"

# The simulator bundles the C++ Booster SDK with its Python package.
sdk_root=/opt/booster/python3/site-packages
if [[ -d "$sdk_root/include" ]]; then
  export CPATH="$sdk_root/include${CPATH:+:$CPATH}"
fi
if [[ -d "$sdk_root/lib" ]]; then
  export LIBRARY_PATH="$sdk_root/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi

# Use --base-paths to only build packages in src directory
# This excludes booster_agent_framework to avoid duplicate package name 'booster_interface'
colcon build  --symlink-install --base-paths src "$@"
build_status=$?
if (( build_status != 0 )); then
  exit "$build_status"
fi

espeak "build complete" >/dev/null 2>&1 || echo "Build complete"
