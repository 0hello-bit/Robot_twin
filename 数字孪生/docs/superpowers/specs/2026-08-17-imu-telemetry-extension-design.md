# TCP 六轴 IMU Telemetry 扩展设计

## 状态

已确认设计。此变更只准备下一次离线 A/B 采集所需的数据链路，不包含烧录、实车控制或融合算法改造。

## 目标

让正式 TCP-only 固件在现有遥测帧中携带 MPU6050 的六轴原始寄存器值、yaw、有效性和可关联的采样序号，并让 PC 采集链路完整保存这些字段。

## 非目标

- 不启用 UDP，也不新增第二条传输通道。
- 不改变电机控制、PID、心跳租约或安全停止逻辑。
- 不在本次变更中宣称完成 IMU 与相机融合或真实位置精度验证。
- 不烧录固件；烧录必须在构建、哈希和目标身份核对完成后另行获得明确授权。
- 不把当前工作区已有的轨迹可视化、采集解耦和治理改动混入本次提交。

## 方案选择

采用在现有 `0x01` telemetry 帧上按 payload 长度扩展的方案。

- 方案 A（采用）：保留现有帧类型，使用长度区分 24、26 和 42 字节版本；旧数据仍可回放，新数据可用于六轴 A/B。
- 方案 B（不采用）：另发独立 IMU 诊断帧。它会引入跨帧配对、丢帧和排序问题，降低时间关联的可解释性。
- 方案 C（不采用）：替换旧 payload。它会破坏已有 24/26 字节历史数据的兼容性。

## Wire Layout

所有多字节字段均为 little-endian。42 字节 payload 的整帧为 47 字节：4 字节头部、42 字节 payload、1 字节 XOR 校验。

| Payload offset | Size | Field | Encoding |
| ---: | ---: | --- | --- |
| 0..3 | 4 | `s0..s3` | `uint8` |
| 4..11 | 8 | `m1..m4` | four `int16` |
| 12..13 | 2 | `error` | `int16` |
| 14..15 | 2 | `pid_output` | `int16` |
| 16..19 | 4 | `tick_ms` | `uint32` |
| 20..23 | 4 | `yaw_deg_x100` | `int32`, degrees multiplied by 100 |
| 24 | 1 | `imu_validity` | `uint8` bit mask |
| 25 | 1 | `imu_init_status` | `uint8` |
| 26..27 | 2 | `imu_ax_raw` | MPU6050 raw `int16` |
| 28..29 | 2 | `imu_ay_raw` | MPU6050 raw `int16` |
| 30..31 | 2 | `imu_az_raw` | MPU6050 raw `int16` |
| 32..33 | 2 | `imu_gx_raw` | MPU6050 raw `int16` |
| 34..35 | 2 | `imu_gy_raw` | MPU6050 raw `int16` |
| 36..37 | 2 | `imu_gz_raw` | MPU6050 raw `int16` |
| 38..41 | 4 | `sample_seq` | `uint32`, telemetry sample sequence |

The six IMU values remain raw counts. Conversion to acceleration and angular-rate units is an offline analysis concern and must use the fixed firmware configuration: accelerometer +/-4g and gyroscope +/-500 degrees/s.

`sample_seq` increments for each telemetry sample queued by the normal firmware path. It is a telemetry sequence, not a claim that every 200 Hz sensor read is transmitted. Missing values expose transport or queue drops instead of being silently renumbered on the PC.

## Batch Capacity

The ESP CIPSEND data limit remains 248 bytes. With 47-byte frames, a batch contains at most 5 frames (235 bytes). The pending queue remains 16 frames deep, so its capacity becomes 752 bytes. The telemetry rate remains unchanged.

## Compatibility

The PC binary parser accepts all three telemetry payload lengths:

- 24 bytes: legacy telemetry, no IMU validity or raw data;
- 26 bytes: current telemetry, yaw plus validity and init status;
- 42 bytes: extended telemetry, yaw/status plus six-axis raw values and `sample_seq`.

For old frames and old JSON, raw fields are `None`, `sample_seq` is `None`, and `imu_raw_known` is `False`. No zero value is promoted to a real sensor observation.

The `V1TelemetryFrame` schema increments its minor version and persists the new optional fields while retaining loading compatibility with prior JSON. `pc_recv_ns` remains a PC-side arrival timestamp and is not added to the wire payload.

## Firmware Changes

The formal `Target 1` project changes only the existing telemetry path:

1. Extend `build_telemetry_frame` and `Telemetry_Queue` parameters with the six `mpu_data` values and `sample_seq`.
2. Increment the sequence at telemetry sample creation and pass the same snapshot values through all normal, line-loss, and hard-stop telemetry paths.
3. Update `TELEMETRY_BATCH_FRAME_SIZE`, send-frame capacity, and their comments so the queue and CIPSEND bounds agree with the 47-byte frame.
4. Keep the existing TCP setup, checksum, ACK/STATUS priority, and retry/clear behavior unchanged.

## PC Changes

1. Extend `decode_telemetry` with the 42-byte layout and explicit `imu_raw_known`/`sample_seq` fields.
2. Pass the decoded values through `capture_sync_run.py` into `V1TelemetryFrame` and JSONL artifacts.
3. Keep the existing yaw unit metadata and distinguish raw-register fields from converted model units.

## Test Contract

The focused tests must prove:

- signed and unsigned field decoding at normal and negative boundary values;
- old 24/26-byte decode behavior remains unchanged;
- three or more concatenated 42-byte frames retain independent boundaries and sequence values;
- the C queue accepts 47-byte frames, retains 16 pending frames, and prepares no more than 5 frames per 248-byte send;
- the firmware source contains all three telemetry call paths with the same IMU snapshot fields;
- the serialized `V1TelemetryFrame` round-trips the optional raw fields and preserves legacy JSON behavior.

## Verification and Release Boundary

After implementation, run the focused Python/C host tests and the full relevant test suite. Then use the F-drive Keil `Target 1` project to build without flashing, record the build log, and compute SHA-256 for the generated HEX and AXF. Report the source commit, target, artifact paths, hashes, and test results.

Only files directly needed for this telemetry extension, its tests, and this design/implementation record may be staged. Existing unrelated dirty files remain untouched. Push the resulting feature commit(s) to the current branch on `origin`; do not force-push and do not push unrelated uncommitted content.
