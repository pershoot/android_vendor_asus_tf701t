#!/system/bin/sh

insmod /system/lib/modules/cfg80211.ko

mmc=mmc2
device=$(cat /sys/bus/sdio/devices/$mmc:0001:1/device)

case $device in
0xa94d) chip=43341
        ;;
*)      chip=4324
        ;;
esac

wifimacwriter /system/etc/nvram_$chip.txt

case $device in
0xa94d) insmod /system/lib/modules/bcmdhd.ko disable_proptx=1 bw_40all=1
        ;;
*)      insmod /system/lib/modules/bcmdhd.ko
        ;;
esac
