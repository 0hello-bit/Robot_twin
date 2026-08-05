# CanMV K230 俯拍定位

本目录按 CanMV K230 MicroPython 官方接口编写：`Sensor.snapshot()` 获取灰度
图像，`image.find_apriltags()` 检测标签，最后通过 UDP `sendto()` 向电脑发送
`x、z、yaw`。电脑端 `live_wifi_bridge.py` 默认监听 UDP `8788`。
每个数据包还包含递增 `sequence`，电脑端会拒绝短时间内重复或乱序的数据包。

## 文件

- `calibrate_floor_tags.py`：使用四个固定标签自动建立像素到地面的单应矩阵。
- `main.py`：识别小车顶部 ID 0 标签并发送实时位姿。
- `k230_config.py`：电脑IP、场地尺寸、标签编号和滤波参数。
- `k230_math.py`：不依赖 OpenCV 的单应矩阵、位姿与滤波计算。

## 使用顺序

1. 给 K230 刷写与开发板匹配的 CanMV MicroPython 固件。
2. 确保 K230 已通过有线网络或开发板支持的 Wi-Fi 接入局域网。
3. 修改 `k230_config.py` 中的 `PC_IP`、标定区域长宽。
4. 在地面四角分别放置标签 10、11、12、13：
   `10=(0,0)`、`11=(宽,0)`、`12=(宽,高)`、`13=(0,高)`。
   对应图片已经生成在上级目录：
   `apriltag_36h11_id10.png` 至 `apriltag_36h11_id13.png`。
5. 在 K230 上运行 `calibrate_floor_tags.py`，连续识别30帧后保存标定。
6. 移除四角标签，在小车顶部放置 ID 0 标签。
7. 在 K230 上运行 `main.py`；电脑调参面板会收到实时位姿。

不同 K230 开发板的联网初始化方式不同，因此本代码假设网络已经连接。拿到
具体开发板后，需要根据板型补充以太网或 Wi-Fi 初始化，摄像头识别和UDP协议
不需要重写。
