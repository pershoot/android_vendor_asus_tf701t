#!/system/bin/sh

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
0xa94d) echo 1 > /sys/module/bcmdhd/parameters/disable_proptx
        ;;
*)
        ;;
esac
