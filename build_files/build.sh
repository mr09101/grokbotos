#!/bin/bash

set -ouex pipefail

# Copy system_files/ from the build context onto the image root.
cp -avf "/ctx/system_files"/. /

# Laptops: NetworkManager-wifi + wpa_supplicant are what make Wi-Fi work at
# all (without them nmcli/nmtui see no wireless devices). iwlwifi-*-firmware
# covers Intel Wi-Fi, alsa-sof-firmware covers Intel SOF audio on most
# 2018+ laptops. foot is the terminal nmtui opens in (grokbot-wifi).
# Electron/Chromium libraries the grok-bot RPM links and does not always
# declare. The RPM's own Requires (gtk3, nss, at-spi2-core, libnotify,
# xdg-utils, libXtst, libuuid) are pulled again by dnf when the RPM is
# installed. Names are Fedora package names, from readelf NEEDED on
# grok-bot 0.71.2 plus the RPM header.
# fedora-cisco-openh264 (ciscobinary.openh264.org) is often unreachable from
# build sandboxes and is only a weak dep of firefox (H.264). Skip it so the
# build does not fail on a mirror timeout.
dnf5 install -y --disablerepo=fedora-cisco-openh264 \
    tmux \
    htop \
    sway \
    swaybg \
    swaylock \
    swayidle \
    sudo \
    openssl \
    wireplumber \
    brightnessctl \
    playerctl \
    wob \
    mako \
    grim \
    slurp \
    wl-clipboard \
    fcitx5 \
    fcitx5-hangul \
    fcitx5-gtk \
    firefox \
    flatpak \
    fuzzel \
    foot \
    NetworkManager-wifi \
    wpa_supplicant \
    iwlwifi-mvm-firmware \
    iwlwifi-dvm-firmware \
    alsa-sof-firmware \
    python3 \
    iproute \
    python3-gobject \
    gtk3 \
    gtk-layer-shell \
    adwaita-icon-theme \
    google-noto-sans-cjk-ttc-fonts \
    xdg-utils \
    fuse \
    fuse-libs \
    curl \
    gtk3 \
    nss \
    nspr \
    at-spi2-core \
    at-spi2-atk \
    libnotify \
    libXtst \
    libuuid \
    libXScrnSaver \
    libXcomposite \
    libXdamage \
    libXfixes \
    libXrandr \
    mesa-libgbm \
    libxkbcommon \
    libdrm \
    alsa-lib \
    cups-libs \
    libsecret \
    systemd-libs

# Brand /usr/lib/os-release (the file /etc/os-release points at) while
# leaving ID and ID_LIKE as fedora. Package managers and bootc key off ID.
sed -i \
    -e 's/^NAME=.*/NAME="Grok Bot OS"/' \
    -e 's/^PRETTY_NAME=.*/PRETTY_NAME="Grok Bot OS"/' \
    /usr/lib/os-release

# fedora-bootc already sets VARIANT="Container Image". Replace it so the
# booted OS identifies itself as Grok Bot OS. Leave ID=fedora alone.
if grep -q '^VARIANT=' /usr/lib/os-release; then
    sed -i 's/^VARIANT=.*/VARIANT="Grok Bot OS"/' /usr/lib/os-release
else
    echo 'VARIANT="Grok Bot OS"' >>/usr/lib/os-release
fi
if grep -q '^VARIANT_ID=' /usr/lib/os-release; then
    sed -i 's/^VARIANT_ID=.*/VARIANT_ID=grok-bot-os/' /usr/lib/os-release
else
    echo 'VARIANT_ID=grok-bot-os' >>/usr/lib/os-release
fi
if ! grep -q '^HOME_URL=' /usr/lib/os-release; then
    echo 'HOME_URL="https://github.com/head77x/grokbotos"' >>/usr/lib/os-release
fi

systemctl enable podman.socket

# fcitx5 ships launchers for its Qt settings tool and a keyboard layout
# viewer. They would show up in the dock and launcher; hide them. Korean
# input is configured by /etc/xdg/fcitx5 (manual/korean-input.md).
for launcher in fcitx5-configtool kbd-layout-viewer5; do
    f="/usr/share/applications/${launcher}.desktop"
    if [[ -f "$f" ]]; then
        sed -i '/^\[Desktop Entry\]/a NoDisplay=true' "$f"
    fi
done
# Right Alt is a 한/영 trigger. Do not let a lone Alt press open
# Firefox's menu bar as well.
cat >/usr/lib64/firefox/defaults/pref/grokbot.js <<'EOF'
pref("ui.key.menuAccessKeyFocuses", false);
EOF

# Screen lock PIN helper (grokbot-lock-setup). sudo ignores files that are
# not 0440 root:root.
chown root:root /etc/sudoers.d/grokbot-lock
chmod 0440 /etc/sudoers.d/grokbot-lock
visudo -cf /etc/sudoers.d/grokbot-lock

# Grok Bot OS API daemon (docs/OS_API.md). A systemd user service, so it
# runs as the session user, never root. --global enables it for every user.
systemctl --global enable grokbotd.service

# OS updates (docs/OS_UPDATES.md): the user decides when to install and
# restart. Fedora's bootc-fetch-apply-updates.timer would download and
# reboot on its own; replace it with a check-only timer, deployment status
# at boot, and the post-update health check that rolls back a bad image.
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service
systemctl enable grokbot-update-check.timer grokbot-update-status.service grokbot-health-check.service
python3 -m py_compile /usr/lib/grokbot/grokbot_update.py /usr/lib/grokbot/grokbot_health.py
python3 -m py_compile /usr/lib/grokbot/grokbotd/*.py /usr/lib/grokbot/grokbot_os_cli.py /usr/lib/grokbot/grokbot_consent.py
bash -n /usr/local/bin/grokbot-webapp

# Default browser for anything that is not the kiosk window itself.
# grokbot-open-browser forces a separate Firefox profile and --new-window.
# The kiosk Firefox is --no-remote on its own profile, so an OAuth or
# download URL cannot replace the Grok Bot screen (2026-07-13).
mkdir -p /etc/xdg
cat >/etc/xdg/mimeapps.list <<'EOF'
[Default Applications]
text/html=grokbot-browser.desktop
x-scheme-handler/http=grokbot-browser.desktop
x-scheme-handler/https=grokbot-browser.desktop
x-scheme-handler/about=grokbot-browser.desktop
x-scheme-handler/unknown=grokbot-browser.desktop
EOF
echo 'BROWSER=/usr/local/bin/grokbot-open-browser' >>/etc/environment

# Default: pinned Grok Bot RPM for this architecture, sha256-checked,
# installed with dnf5 --setopt=tsflags=noscripts, then moved out of
# /opt. GROKBOT_DISABLE_BUNDLED_APP=1 keeps the Firefox placeholder.
# See build_files/install-grokbot-app.sh.
/ctx/install-grokbot-app.sh

# Kiosk account, separate from the admin user Anaconda creates at install
# time. The password stays locked; tty1 autologin does not ask for one.
# --create-home writes /var/home at build time, which may not ship.
# system_files/usr/lib/tmpfiles.d/grokbot-home.conf recreates it on boot.
useradd --create-home --shell /usr/local/bin/grokbot-session grokbot
