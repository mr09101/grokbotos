#!/bin/bash
# Shared assertions for the Grok Bot OS shell tests.

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_eq() {
    local got="$1"
    local want="$2"
    [[ "$got" == "$want" ]] || fail "expected [${want}] got [${got}]"
}

assert_file() {
    [[ -f "$1" ]] || fail "missing file $1"
}

assert_contains() {
    local file="$1"
    local needle="$2"
    grep -F -q -- "$needle" "$file" || fail "${file} does not contain: ${needle}"
}

# Binaries the scripts may call, without leaking a system firefox/flatpak/fuzzel
# onto PATH ahead of the fakes.
make_core_path() {
    local dest="$1"
    local tool bin
    mkdir -p "$dest"
    for tool in mkdir realpath rm cat chmod cp find sed awk sha256sum install mktemp mv ln basename id dirname grep head tr date bash; do
        bin=$(command -v "$tool" || true)
        if [[ -n "$bin" ]]; then
            ln -sf "$bin" "${dest}/${tool}"
        fi
    done
}
