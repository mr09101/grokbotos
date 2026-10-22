#!/bin/bash
# grokbotd daemon, grokbot-os CLI, MCP server and backends (tests/grokbotd/).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
python3 -m unittest discover -s "${root}/tests/grokbotd" -p 'test_*.py'
echo "PASS test-grokbotd.sh"
