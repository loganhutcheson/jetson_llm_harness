----- IMX219 CAM1 Bring-Up -----
This repo does not yet consume camera frames in-process, but the Jetson bring-up
for a CSI camera on CAM1 is now documented here because the boot flow was
hardware-specific and non-obvious.

Working module:
- Sony IMX219-compatible module on CAM1

Validated runtime result:
- live DT contains `cam_i2cmux`
- live DT contains `rbpcv2_imx219_c@10`
- `/dev/video0` exists
- kernel logs show `imx219 9-0010` bound
- Argus capture succeeds

Root cause we hit:
- `/boot/extlinux/extlinux.conf` and `/boot/dtb/...imx219-c.merged.dtb` looked correct
- but the Jetson was actually booting its runtime DTB from the dedicated
  `A_kernel-dtb` / `B_kernel-dtb` partitions
- both DTB partitions were missing the IMX219 CAM1 nodes, so the live device tree
  never gained `cam_i2cmux` or `imx219`, and no camera registered at runtime

Fix:
- write the merged CAM1 DTB into both `A_kernel-dtb` and `B_kernel-dtb`
- reboot

Helper:
- `jetson/camera/force_imx219_cam1_dtb.sh`

Recommended workflow on the Jetson:
1. Confirm the merged DTB on disk contains the sensor:
   `strings /boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.imx219-c.merged.dtb | egrep -i 'imx219|cam_i2cmux|rbpcv2'`
2. Apply it to the DTB partitions:
   `sudo ./jetson/camera/force_imx219_cam1_dtb.sh --reboot`
3. After reboot, confirm the live tree and device nodes:
   `find /sys/firmware/devicetree/base -iname '*imx219*' -o -iname '*cam_i2cmux*'`
   `ls -l /dev/video* /dev/media* 2>/dev/null`
4. Check the kernel probe path:
   `sudo dmesg | egrep -i 'imx219|camera|nvcsi|vi5|csi'`
5. Take a test photo:
   `gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 num-buffers=1 ! 'video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1' ! nvjpegenc ! filesink location=/tmp/imx219_cam1_test.jpg`
6. Validate the image file:
   `file /tmp/imx219_cam1_test.jpg`

Expected healthy indicators:
- `imx219 9-0010: tegracam sensor driver:imx219_v2.0.6`
- `tegra-camrtc-capture-vi ... subdev imx219 9-0010 bound`
- `/tmp/imx219_cam1_test.jpg: JPEG image data ... 1920x1080`

Notes:
- On this board, the camera registered on Linux I2C bus `9` at address `0x10`.
- `i2cdetect -y -r 9` should show `UU` at `0x10` once the driver has claimed it.
- This confirmed still capture through Argus. It did not validate autofocus control;
  AF support may depend on the exact camera vendor and userspace control path.
