#!/bin/sh
set -eu

cd /workspace

if [ -f fix.patch ]; then
  git apply --whitespace=fix fix.patch 2>/dev/null || patch -p1 < fix.patch
fi

exec "$@"
