#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

status=0
for test_file in "${root}"/tests/test-*.sh; do
    echo "== ${test_file#"${root}"/}"
    if bash "$test_file"; then
        :
    else
        status=1
    fi
done

if command -v shellcheck >/dev/null 2>&1; then
    echo "== shellcheck"
    shellcheck \
        build_files/*.sh \
        system_files/usr/local/bin/grokbot-* \
        system_files/usr/lib/grokbot/*.sh \
        tests/*.sh
else
    echo "SKIP shellcheck: not installed"
fi

exit "$status"
