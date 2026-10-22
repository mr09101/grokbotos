#!/bin/bash
# OS update / rollback test images for the VM (docs/OS_UPDATES.md).
#   sudo -E tools/vm/update-test.sh registry      start a local registry on :5000 (plain http)
#   sudo -E tools/vm/update-test.sh push TAG VER [broken]
#        build TAG on top of $GBVM_IMAGE: label version VER, a marker file
#        /usr/share/grokbot/test-image (= TAG); "broken" makes grokbotd exit
#        at start so the post-update health check must roll back.
#        Pushed as localhost:5000/grokbotos:TAG and :latest.
#   sudo -E tools/vm/update-test.sh disk TAG       VM disk installed from :TAG,
#        taking updates from 10.0.2.2:5000/grokbotos:latest (the host as the VM sees it)
# Test-only: nothing here goes into the image.
set -euo pipefail
here=$(dirname "$0")
# shellcheck source=tools/vm/common.sh
source "$here/common.sh"
REG=localhost:5000
case ${1:-} in
registry)
    podman container exists gbreg || podman run -d --name gbreg -p 5000:5000 docker.io/library/registry:2
    podman start gbreg >/dev/null ;;
push)
    tag=$2 ver=$3 mode=${4:-}
    ctx=$(mktemp -d)
    {
        echo "FROM $GBVM_IMAGE"
        echo "LABEL org.opencontainers.image.version=\"$ver\""
        echo "RUN echo $tag > /usr/share/grokbot/test-image"
        if [[ $mode == broken ]]; then
            echo "RUN mkdir -p /usr/lib/systemd/user/grokbotd.service.d && printf '[Service]\\nExecStart=\\nExecStart=/bin/false\\nRestart=no\\n' > /usr/lib/systemd/user/grokbotd.service.d/zz-test-broken.conf"
        fi
    } >"$ctx/Containerfile"
    podman build -t "$REG/grokbotos:$tag" "$ctx"
    rm -rf "$ctx"
    podman push --tls-verify=false "$REG/grokbotos:$tag"
    podman tag "$REG/grokbotos:$tag" "$REG/grokbotos:latest"
    podman push --tls-verify=false "$REG/grokbotos:latest" ;;
disk)
    GBVM_SOURCE_IMGREF="docker://$REG/grokbotos:$2" GBVM_TARGET_IMGREF="10.0.2.2:5000/grokbotos:latest" \
    GBVM_INSECURE_REGISTRIES="$REG 10.0.2.2:5000" GBVM_IMAGE="$REG/grokbotos:$2" "$here/mkdisk.sh" ;;
*)
    sed -n '2,13p' "$0"; exit 2 ;;
esac
