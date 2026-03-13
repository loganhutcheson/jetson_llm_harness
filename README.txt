----- Build Commands -----
cmake -S . -B build
cmake --build build -j
./build/jetson_runtime

On the Jetson, install cmake once with:
sudo apt-get install -y cmake

----- IMU Runtime Config -----
Default behavior uses the synthetic IMU path so local builds keep working.

To enable a real MPU-6050 on the Jetson at runtime:
JETSON_IMU_SOURCE=mpu6050
JETSON_IMU_ENABLE=1
JETSON_IMU_I2C_DEV=/dev/i2c-7
JETSON_IMU_I2C_ADDR=0x68

Notes:
- On the Jetson Orin Nano dev kit, 40-pin header pins `3/5` map to Linux bus `/dev/i2c-7`.
- `JETSON_IMU_I2C_ADDR` may be `0x68` or `0x69` depending on AD0 wiring.
- The runtime logs the active IMU source at startup and falls back to the stub if init fails.
- The periodic IMU log includes sample rate plus one recent accel/gyro sample for hardware bring-up.
- Accelerometer values are published in m/s^2, so the existing motion check still expects gravity near 9.81.

----- OLED Runtime Config -----
To enable the 128x64 OLED on the same I2C bus:
JETSON_OLED_ENABLE=1
JETSON_OLED_I2C_DEV=/dev/i2c-7
JETSON_OLED_I2C_ADDR=0x3c

Notes:
- The repo uses a raw userspace OLED driver in C++, not `luma.oled`.
- The OLED module on the current Jetson setup is detected at address `0x3c`.

----- Buzzer Wiring -----
For a simple 3-pin active buzzer module on the Jetson Orin Nano 40-pin header:
JETSON_BUZZER_ENABLE=1
JETSON_BUZZER_PIN=7
JETSON_BUZZER_ACTIVE_LOW=1

Suggested wiring:
- buzzer `I/O` -> physical pin `7`
- buzzer `GND` -> physical pin `14`
- buzzer `VCC` -> physical pin `17` (`3.3V`)

Notes:
- This buzzer wiring is active-low on the current Jetson setup.

Quick run command:
JETSON_IMU_SOURCE=mpu6050
JETSON_IMU_ENABLE=1
JETSON_OLED_ENABLE=1
JETSON_BUZZER_ENABLE=1
JETSON_BUZZER_PIN=7
JETSON_BUZZER_ACTIVE_LOW=1
./build/jetson_runtime
