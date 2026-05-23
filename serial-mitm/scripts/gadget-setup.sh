#!/bin/bash
modprobe libcomposite

cd /sys/kernel/config/usb_gadget
mkdir -p g1 && cd g1

echo 0x1210 > idVendor
echo 0x0032 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "" > strings/0x409/serialnumber
echo "" > strings/0x409/manufacturer
echo "DigiTech RP360" > strings/0x409/product

mkdir -p functions/acm.usb0
mkdir -p configs/c.1/strings/0x409
echo "CDC ACM" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower
ln -sf functions/acm.usb0 configs/c.1/

ls /sys/class/udc > UDC
echo "Gadget actif."
