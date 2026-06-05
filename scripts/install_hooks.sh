#!/usr/bin/env bash
# Configure git to use the versioned .githooks directory.
#
# Run once after cloning. Re-run is harmless.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config core.hooksPath .githooks
echo "git hooks installed (core.hooksPath = .githooks)"
echo
echo "Active hooks:"
ls -1 .githooks/ | grep -v '\.sample$'
