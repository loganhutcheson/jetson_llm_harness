# Jetson Runtime Notes

## Jetson Orin Nano IMU bring-up
- On the Jetson Orin Nano dev kit 40-pin header, physical pins `3/5` are the active I2C pair for the MPU-6050 bring-up, but on Linux they show up on `/dev/i2c-7`.
- Probing `/dev/i2c-1` can be misleading on this platform because the header I2C bus for pins `3/5` is exposed as bus `7`.
- `i2cdetect -y -r 7` is the quickest validation step for header pins `3/5`.
- With `AD0` tied to ground, the expected MPU-6050 address is `0x68`.

## Runtime defaults
- The repo defaults the MPU runtime config to `/dev/i2c-7` and `0x68`.
- The real IMU path is enabled with:
  - `JETSON_IMU_SOURCE=mpu6050`
  - `JETSON_IMU_ENABLE=1`
  - `JETSON_IMU_I2C_DEV=/dev/i2c-7`
  - `JETSON_IMU_I2C_ADDR=0x68`

## Jetson validation
- Install `cmake` on the Jetson with:
  - `sudo apt-get install -y cmake`
- If `cmake` is still unavailable on the Jetson, the project can still be compiled directly with:
  - `/usr/bin/c++ -std=c++20 -O2 -Isrc src/main.cpp -pthread -o jetson_runtime`
- A healthy real-IMU startup looks like:
  - `[main] IMU source=mpu6050(/dev/i2c-7, addr=0x68)`
- A healthy periodic IMU log looks like:
  - `[imu] hz=... total=... dropped=0 sample.seq=... accel=(ax,ay,az) gyro=(gx,gy,gz)`
- A healthy OLED/buzzer startup looks like:
  - `[main] oled enabled=1`
  - `[main] buzzer enabled=1 pin=7`
- A healthy completion path looks like:
  - `[LCD]`
  - `  RUN COMPLETE`
  - `  cam=... imu=...`

## Jetson DTB and GPIO checks
- To confirm which header overlay will load on next boot:
  - `grep -n 'OVERLAYS' /boot/extlinux/extlinux.conf`
- To inspect the pin-7 overlay contents directly on the Jetson:
  - `fdtdump /boot/pin7_as_gpio.dtbo 2>/dev/null | sed -n '1,220p'`
- The current pin-7 overlay fixes header pin `7` up as `soc_gpio59_pac6` (`PAC.06`).
- A broken pin-7 overlay can still look present in `extlinux.conf` but leave the pad undriven if it omits:
  - `nvidia,function = "gp"`
  - `nvidia,gpio-mode = <1>`
  - `nvidia,tristate = <0>`
- For JetPack builds where the GitHub `pin7_as_gpio` overlay is still treated as input-only after reboot, replace `/boot/pin7_as_gpio.dtbo` with a stronger variant that includes:
  - `nvidia,function = "gp"`
  - `nvidia,gpio-mode = <1>`
  - `nvidia,tristate = <0>`
  - `nvidia,enable-input = <1>`
  - `nvidia,pull = <0>`
- To confirm the live kernel GPIO line after boot:
  - `gpioinfo | grep -n 'PAC.06'`
- A healthy pin-7 result looks like:
  - `line 144: "PAC.06" unused input active-high`
- To confirm the pinmux is not still tristated:
  - `printf 'Lablab123\n' | sudo -S sed -n '2178,2196p' /sys/kernel/debug/pinctrl/2430000.pinmux/pinconf-groups`
- A broken pinmux state shows `tristate=1`; the fixed overlay should come back with `gpio-mode=1` and `tristate=0`.
- On this Jetson, the overlay alone was not sufficient: after reboot the live PADCTL register at `0x2448030` still came up as `0x5a`, so board pin `7` stayed input + tristate.
- The working runtime fix was a Jetson-local systemd unit that writes PADCTL `0x2448030 = 0x0a` at boot. Those host-local files are not in this repo:
  - `/usr/local/sbin/pin7_padctl_fix.sh`
  - `/etc/systemd/system/pin7-padctl-fix.service`
- The buzzer on pin `7` is active-low in this setup, so runtime env should include:
  - `JETSON_BUZZER_ACTIVE_LOW=1`
- To verify the live PADCTL value on the Jetson:
  - `printf 'Lablab123\n' | sudo -S python3 -c 'import mmap,os,struct; addr=0x2448030; page=addr & ~(mmap.PAGESIZE-1); off=addr-page; fd=os.open("/dev/mem", os.O_RDONLY|os.O_SYNC); mm=mmap.mmap(fd, mmap.PAGESIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=page); print(hex(struct.unpack("<I", mm[off:off+4])[0])); mm.close(); os.close(fd)'`
- `0x5a` is the broken state; `0x0a` is the working state that allows `Jetson.GPIO` output on board pin `7`.

## OLED bring-up
- The 128x64 OLED module on the current Jetson setup is on `/dev/i2c-7` at `0x3c`.
- `luma.oled` did not render correctly for this module; the working solution is the repo's raw C++ userspace OLED driver.
- The OLED demo target is:
  - `oled_demo`
- The main runtime target is:
  - `jetson_runtime`
