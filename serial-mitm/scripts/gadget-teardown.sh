#!/bin/bash
cd /sys/kernel/config/usb_gadget/g1 2>/dev/null || { echo "Gadget non actif."; exit 1; }

echo "" > UDC
rm -f configs/c.1/acm.usb0
rmdir configs/c.1/strings/0x409
rmdir configs/c.1
rmdir functions/acm.usb0
rmdir strings/0x409
cd /sys/kernel/config/usb_gadget
rmdir g1

modprobe -r libcomposite
echo "Gadget désactivé."
