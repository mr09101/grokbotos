#!/bin/bash
# Build a bootable UEFI test disk from a locally built image, without an installer.
# usage: sudo -E tools/vm/mkdisk.sh [out.qcow2]
# Optional local-only recovery user (never commit real values):
#   GBVM_TEST_USER=name GBVM_TEST_PASS=secret sudo -E tools/vm/mkdisk.sh
# Update tests (tools/vm/update-test.sh): install from a registry and take
# updates from it. Test-only, never in the image:
#   GBVM_SOURCE_IMGREF=docker://localhost:5000/grokbotos:a   install source
#   GBVM_TARGET_IMGREF=10.0.2.2:5000/grokbotos:latest        where updates come from
#   GBVM_INSECURE_REGISTRIES="localhost:5000 10.0.2.2:5000"   plain-http registries
# For a real install test, prefer `bootc install to-disk` (agents/skills/install-testing.md).
set -euo pipefail
# shellcheck source=tools/vm/common.sh
source "$(dirname "$0")/common.sh"
export PATH=$PATH:/usr/sbin
out=${1:-$GBVM_DIR/disk.qcow2}
raw=$GBVM_DIR/disk.raw
mnt=$GBVM_DIR/mnt
cleanup() { umount -R "$mnt" 2>/dev/null || true; [[ -n ${l1:-} ]] && losetup -d "$l1" "$l2" "${l3:-}" 2>/dev/null || true; }
trap cleanup EXIT
rm -f "$raw"; truncate -s 20G "$raw"
sgdisk -Z -n1:2048:+600M -t1:ef00 -c1:EFI-SYSTEM -n3:0:+1G -t3:8300 -c3:boot -n2:0:0 -t2:8304 -c2:root "$raw"
part() { sgdisk -i"$1" "$raw" | awk -v k="$2" '$0 ~ k {print $3}'; }
s1=$(part 1 'First sector'); e1=$(part 1 'Last sector')
s2=$(part 2 'First sector'); e2=$(part 2 'Last sector')
s3=$(part 3 'First sector'); e3=$(part 3 'Last sector')
l1=$(losetup -f --show -o $((s1 * 512)) --sizelimit $(((e1 - s1 + 1) * 512)) "$raw")
l2=$(losetup -f --show -o $((s2 * 512)) --sizelimit $(((e2 - s2 + 1) * 512)) "$raw")
# separate /boot like a real install: ostree finalize must be able to remount it rw
l3=$(losetup -f --show -o $((s3 * 512)) --sizelimit $(((e3 - s3 + 1) * 512)) "$raw")
mkfs.vfat -F32 -n EFI-SYSTEM "$l1"; mkfs.xfs -f -L root "$l2"; mkfs.xfs -f -L boot "$l3"
u2=$(blkid -s UUID -o value "$l2"); u3=$(blkid -s UUID -o value "$l3")
mkdir -p "$mnt"; mount "$l2" "$mnt"; mkdir -p "$mnt/boot"; mount "$l3" "$mnt/boot"; mkdir -p "$mnt/boot/efi"; mount -t tmpfs tmpfs "$mnt/boot/efi"
regconf=$GBVM_DIR/99-gbvm-insecure.conf
: >"$regconf"
for r in ${GBVM_INSECURE_REGISTRIES:-}; do printf '[[registry]]\nlocation = "%s"\ninsecure = true\n\n' "$r" >>"$regconf"; done
extra=()
[[ -n ${GBVM_SOURCE_IMGREF:-} ]] && extra+=(--source-imgref "$GBVM_SOURCE_IMGREF")
[[ -n ${GBVM_TARGET_IMGREF:-} ]] && extra+=(--target-imgref "$GBVM_TARGET_IMGREF")
podman run --rm --privileged --pid=host --net=host --security-opt label=type:unconfined_t \
    -v /var/lib/containers:/var/lib/containers -v /dev:/dev -v /run/udev:/run/udev -v "$mnt:/target" \
    -v "$regconf:/etc/containers/registries.conf.d/99-gbvm-insecure.conf:ro" \
    "$GBVM_IMAGE" bootc install to-filesystem "${extra[@]}" --skip-fetch-check --disable-selinux --bootloader=none \
    --root-mount-spec="UUID=$u2" --boot-mount-spec="UUID=$u3" --karg=console=tty0 --karg=console=ttyS0 \
    --karg=enforcing=0 --karg=video=Virtual-1:1280x800 /target
mountpoint -q "$mnt" && mount -o remount,rw "$mnt" || mount "$l2" "$mnt"
mountpoint -q "$mnt/boot" || mount "$l3" "$mnt/boot"; mkdir -p "$mnt/boot/efi"; mountpoint -q "$mnt/boot/efi" || mount -t tmpfs tmpfs "$mnt/boot/efi"
dep=$(ls -d "$mnt"/ostree/deploy/default/deploy/*.0)
if [[ -s $regconf ]]; then
    mkdir -p "$dep/etc/containers/registries.conf.d"
    cp "$regconf" "$dep/etc/containers/registries.conf.d/99-gbvm-insecure.conf"
fi
if [[ -n ${GBVM_HEALTH_TIMEOUT:-} ]]; then
    printf '[health]\ntimeout_s = %s\n' "$GBVM_HEALTH_TIMEOUT" >"$dep/etc/grokbot/health.conf"
fi
if [[ -n ${GBVM_TEST_USER:-} ]]; then
    [[ -n ${GBVM_TEST_PASS:-} ]] || { echo "GBVM_TEST_PASS is required with GBVM_TEST_USER" >&2; exit 2; }
    hash=$(openssl passwd -6 "$GBVM_TEST_PASS")
    echo "$GBVM_TEST_USER:x:1500:1500::/var/home/$GBVM_TEST_USER:/bin/bash" >> "$dep/etc/passwd"
    echo "$GBVM_TEST_USER:x:1500:" >> "$dep/etc/group"
    sed -i "s/^wheel:x:10:\$/&$GBVM_TEST_USER/; t; s/^wheel:x:10:.*/&,$GBVM_TEST_USER/" "$dep/etc/group"
    echo "$GBVM_TEST_USER:$hash:20000:0:99999:7:::" >> "$dep/etc/shadow"
fi
podman run --rm -v "$mnt/boot/efi:/esp" "$GBVM_IMAGE" sh -c \
    'mkdir -p /esp/EFI/BOOT /esp/EFI/fedora && cp /usr/lib/efi/grub2/*/EFI/fedora/grubx64.efi /esp/EFI/BOOT/BOOTX64.EFI && cp /usr/lib/efi/grub2/*/EFI/fedora/grubx64.efi /esp/EFI/fedora/'
for f in "$mnt/boot/efi/EFI/BOOT/grub.cfg" "$mnt/boot/efi/EFI/fedora/grub.cfg"; do
    cat > "$f" <<G
search --no-floppy --fs-uuid --set=root $u3
set boot=\$root
set timeout=3
insmod blscfg
blscfg
G
done
(cd "$mnt/boot/efi" && mcopy -s -o -i "$l1" ./* ::/)
cleanup; trap - EXIT
qemu-img convert -O qcow2 "$raw" "$out"; rm -f "$raw"
echo "wrote $out"
