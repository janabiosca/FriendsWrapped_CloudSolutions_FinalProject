#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
package_dir="$project_dir/infra/wrapped/.build/package"
mkdir -p "$package_dir"
python3 -m pip install --requirement "$project_dir/requirements-wrapped.txt" \
  --target "$package_dir" --upgrade --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --implementation cp --python-version 3.13
cp "$project_dir"/src/*.py "$package_dir/"
