#!/bin/bash
# Security review #2: updates are accepted only with a valid cosign
# signature for the Grok Bot OS images.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
cd "$root"
python3 - <<'PY'
import json, sys
p = json.load(open("system_files/etc/containers/policy.json"))
d = p["transports"]["docker"]
for repo in ("ghcr.io/head77x/grokbotos", "ghcr.io/head77x/grokbotos-arm64"):
    r = d[repo]
    assert len(r) == 1 and r[0]["type"] == "sigstoreSigned", repo
    assert r[0]["keyPath"] == "/etc/pki/containers/grokbotos.pub", repo
    assert r[0]["signedIdentity"]["type"] == "matchRepository", repo
for repo, reqs in d.items():
    assert all(x["type"] != "insecureAcceptAnything" for x in reqs) or "grokbotos" not in repo, repo
PY
cmp -s cosign.pub system_files/etc/pki/containers/grokbotos.pub || fail "grokbotos.pub differs from cosign.pub"
for r in grokbotos grokbotos-arm64; do
    grep -A1 "ghcr.io/head77x/${r}:" system_files/etc/containers/registries.d/grokbotos.yaml |
        grep -q "use-sigstore-attachments: true" || fail "no sigstore attachments for $r"
done
# Not --enforce-container-sigpolicy: bootc then refuses any policy whose
# default is insecureAcceptAnything (seen in the VM), and the default must
# stay open for other images. The per-repository requirement above is
# applied by containers/image on every pull anyway.
grep -q -- "bootc switch --mutate-in-place --transport registry ghcr.io/head77x/grokbotos:latest" \
    disk_config/iso.toml || fail "kickstart switch line changed"
python3 -c 'import json;assert json.load(open("system_files/etc/containers/policy.json"))["default"][0]["type"]=="insecureAcceptAnything"' 
echo "PASS test-sigpolicy.sh"
