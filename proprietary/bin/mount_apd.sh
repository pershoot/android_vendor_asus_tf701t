#!/system/bin/sh

# This service is for ASUS Product Demo

mount -t ext4 /dev/block/platform/sdhci-tegra.3/by-name/APD /APD
chown system:system /APD
chmod 0775 /APD
