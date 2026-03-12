----- Build Commands -----
cmake -S . -B build
cmake --build build -j

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
