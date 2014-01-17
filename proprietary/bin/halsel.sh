#! /system/bin/sh
SRC=/system/lib/hw
TGT=/data/sensors/hw/sensors.macallan.so

case `cat /sys/devices/platform/asustek_pcbid/asustek_projectid` in
00) rm -f $TGT; ln -s $SRC/sensors.mozart.so $TGT;;
02) rm -f $TGT; ln -s $SRC/sensors.haydn.so  $TGT;;
*)  ;;
esac
