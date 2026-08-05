"""esp01s_setup.py - ESP01S WiFi 配置工具

通过 USB 转串口或 STM32 的 UART 配置 ESP01S。
将 ESP01S 设为 Station 模式，连接 WiFi，开启 TCP Server。

使用:
    python wireless/esp01s_setup.py               # 交互式配置
    python wireless/esp01s_setup.py --ssid MyWiFi --password 12345678  # 一键配置

接线 (USB 转串口):
    USB2TTL       ESP01S
    TXD      ->   RXD
    RXD      ->   TXD
    VCC(3.3V) ->  VCC
    GND      ->   GND
    GND      ->   IO0 (拉低进入烧录模式，可选)
    3.3V     ->   CH_PD(EN)

注意: ESP01S 是 3.3V 电平，不能用 5V！
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# AT 命令列表
AT_COMMANDS = {
    "test":           "AT\r\n",
    "reset":          "AT+RST\r\n",
    "version":        "AT+GMR\r\n",
    "mode_station":   "AT+CWMODE=1\r\n",
    "mode_softap":    "AT+CWMODE=2\r\n",
    "mode_both":      "AT+CWMODE=3\r\n",
    "join":           'AT+CWJAP="{}","{}"\r\n',
    "quit_ap":        "AT+CWQAP\r\n",
    "get_ip":         "AT+CIFSR\r\n",
    "tcp_server":     'AT+CIPSERVER=1,{}\r\n',
    "tcp_stop":       "AT+CIPSERVER=0\r\n",
    "tcp_send":       "AT+CIPSEND={}\r\n",
    "tcp_status":     "AT+CIPSTATUS\r\n",
    "trans_start":    "AT+CIPMODE=1\r\n",
    "trans_stop":     "AT+CIPMODE=0\r\n",
    "uart_def":       "AT+UART_DEF=115200,8,1,0,0\r\n",
    "uart_38400":     "AT+UART_DEF=38400,8,1,0,0\r\n",
    "uart_9600":      "AT+UART_DEF=9600,8,1,0,0\r\n",
}


class ESP01SConfig:
    def __init__(self, port=None, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def open(self):
        try:
            import serial
        except ImportError:
            print("pyserial not installed. Use USB-TTL adapter on another PC, or")
            print("configure ESP01S via the AT command passthrough method.")
            return False

        if not self.port:
            # Auto-detect
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            if not ports:
                print("No serial ports found")
                return False
            for p in ports:
                print(f"  {p.device}: {p.description}")
            if len(ports) == 1:
                self.port = ports[0].device
            else:
                idx = input(f"Select port (1-{len(ports)}): ")
                try:
                    self.port = ports[int(idx)-1].device
                except:
                    return False

        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
            time.sleep(0.5)
            return True
        except Exception as e:
            print(f"Open failed: {e}")
            return False

    def close(self):
        if self.ser:
            self.ser.close()

    def send_at(self, cmd, wait_ms=1000):
        """发送 AT 命令并返回响应"""
        if not self.ser:
            return ""
        self.ser.write(cmd.encode())
        self.ser.flush()
        time.sleep(wait_ms / 1000.0)
        response = b""
        while self.ser.in_waiting:
            response += self.ser.read(self.ser.in_waiting)
            time.sleep(0.05)
        return response.decode("utf-8", errors="replace").strip()

    def test_connection(self):
        """测试 AT 通信"""
        print("\n[1/6] Testing AT communication...")
        resp = self.send_at(AT_COMMANDS["test"], 500)
        if "OK" in resp:
            print("  OK - AT response received")
            return True
        print(f"  No response. Try different baud rate.")
        print(f"  Response: {resp[:100]}")
        return False

    def set_mode(self, mode="station"):
        """设置 WiFi 模式"""
        print(f"\n[2/6] Setting WiFi mode to {mode}...")
        cmd = AT_COMMANDS[f"mode_{mode}"]
        resp = self.send_at(cmd, 500)
        if "OK" in resp or "no change" in resp:
            print(f"  OK - Mode set to {mode}")
            return True
        print(f"  Failed: {resp[:100]}")
        return False

    def connect_wifi(self, ssid, password):
        """连接 WiFi"""
        print(f"\n[3/6] Connecting to WiFi '{ssid}'...")
        cmd = AT_COMMANDS["join"].format(ssid, password)
        resp = self.send_at(cmd, 8000)
        if "OK" in resp or "CONNECT" in resp or "ALREADY CONNECT" in resp:
            print(f"  OK - Connected to {ssid}")

            # Get IP
            time.sleep(1)
            ip_resp = self.send_at(AT_COMMANDS["get_ip"], 500)
            for line in ip_resp.split("\r\n"):
                if "+CIFSR" in line or "STAIP" in line or '"' in line:
                    print(f"  IP: {line.strip()}")
            return True
        print(f"  Failed: {resp[:200]}")
        print("  Tips: Check SSID/password, router 2.4GHz only")
        return False

    def set_baudrate(self, baudrate):
        """设置 UART 波特率"""
        print(f"\n[4/6] Setting UART baudrate to {baudrate}...")
        key = f"uart_{baudrate}" if baudrate in (9600, 38400) else "uart_def"
        cmd = AT_COMMANDS.get(key, AT_COMMANDS["uart_def"])
        resp = self.send_at(cmd, 500)
        if "OK" in resp:
            print(f"  OK - Baudrate set to {baudrate}")
            # Reconnect with new baudrate
            self.baudrate = baudrate
            self.close()
            self.open()
            return True
        print(f"  Warning: {resp[:100]}")
        return False

    def start_tcp_server(self, port=8888):
        """启动普通 TCP Server；固件使用 AT+CIPSEND 发送数据。"""
        print(f"\n[5/6] Starting TCP server on port {port}...")

        # Keep normal mode so STM32 can use AT+CIPSEND with a client id.
        resp = self.send_at(AT_COMMANDS["trans_stop"], 500)
        if "OK" in resp or "no change" in resp.lower():
            print("  OK - Normal TCP mode enabled")
        else:
            print(f"  Warning: {resp[:100]}")

        # Start server
        cmd = AT_COMMANDS["tcp_server"].format(port)
        resp = self.send_at(cmd, 1000)
        if "OK" in resp or "already" in resp.lower():
            print(f"  OK - TCP server started on port {port}")
            return True
        print(f"  Failed: {resp[:100]}")
        return False

    def show_status(self):
        """显示当前状态"""
        print(f"\n[6/6] Current status:")
        resp = self.send_at(AT_COMMANDS["tcp_status"], 500)
        for line in resp.split("\r\n"):
            if line.strip():
                print(f"  {line.strip()}")
        resp = self.send_at(AT_COMMANDS["get_ip"], 500)
        for line in resp.split("\r\n"):
            if line.strip():
                print(f"  {line.strip()}")


def configure_via_at_passhtrough(stm32_port, stm32_baud=38400):
    """通过 STM32 的 UART 透传配置 ESP01S"""
    print("=" * 50)
    print("  STM32 UART Passthrough Mode")
    print("=" * 50)
    print()
    print("  Steps:")
    print("  1. Connect ESP01S to STM32 (TXD->PA10, RXD->PA9)")
    print("  2. Power up both")
    print("  3. This script sends AT commands via STM32's UART")
    print()
    print("  This requires a custom STM32 firmware that")
    print('  forwards UART data bidirectionally ("passthrough").')
    print("  Alternatively, use a USB-TTL adapter directly.")
    print()
    return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="ESP01S WiFi Configuration Tool")
    parser.add_argument("--port", help="Serial port (e.g. COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="ESP01S default baudrate")
    parser.add_argument("--ssid", help="WiFi SSID")
    parser.add_argument("--password", help="WiFi password")
    parser.add_argument("--tcp-port", type=int, default=8888, help="TCP server port")
    parser.add_argument("--station-baud", type=int, default=38400,
                        help="Baudrate for STM32 communication (after setup)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick setup: assumes ESP01S is already at default AT baud")
    args = parser.parse_args()

    print("=" * 50)
    print("  ESP01S WiFi 配置工具")
    print("  HC-06 -> ESP01S 替换助手")
    print("=" * 50)

    if args.ssid:
        # Quick non-interactive mode
        cfg = ESP01SConfig(args.port, args.baud)
        if not cfg.open():
            return
        if not cfg.test_connection():
            cfg.close()
            return
        cfg.set_mode("station")
        cfg.connect_wifi(args.ssid, args.password)
        cfg.set_baudrate(args.station_baud)
        cfg.start_tcp_server(args.tcp_port)
        cfg.show_status()
        cfg.close()
        print_config_summary(args.ssid, args.tcp_port, args.station_baud)
        return

    # Interactive mode
    cfg = ESP01SConfig(args.port, args.baud)
    if not cfg.open():
        configure_via_at_passhtrough(None)
        return

    if not cfg.test_connection():
        # Try other baudrates
        for br in [9600, 38400, 57600, 74880, 115200]:
            if br == args.baud:
                continue
            print(f"Trying {br} baud...")
            cfg.baudrate = br
            cfg.close()
            if cfg.open() and cfg.test_connection():
                break
        else:
            print("Could not connect to ESP01S at any baudrate.")
            cfg.close()
            return

    cfg.set_mode("station")

    ssid = args.ssid or input("WiFi SSID: ")
    password = args.password or input("WiFi Password: ")
    cfg.connect_wifi(ssid, password)

    # Set baudrate to match STM32
    station_baud = args.station_baud
    print(f"\nSet UART baudrate to {station_baud} (matching STM32)...")
    cfg.set_baudrate(station_baud)

    cfg.start_tcp_server(args.tcp_port)
    cfg.show_status()
    cfg.close()

    print_config_summary(ssid, args.tcp_port, station_baud)


def print_config_summary(ssid, port, baud):
    print()
    print("=" * 50)
    print("  ESP01S 配置完成!")
    print("=" * 50)
    print(f"  WiFi:      {ssid}")
    print(f"  TCP Port:  {port}")
    print(f"  UART:      {baud} baud")
    print()
    print("  在数字孪生中连接:")
    print(f'  bridge = WifiBridge()')
    print(f'  bridge.connect("192.168.x.x", {port})')
    print(f'  bridge.start()')
    print()
    print("  Tips:")
    print("  1. ESP01S 的 IP 可以在路由器管理页面查看")
    print("  2. 也可以用 AT+CIFSR 查询 IP")
    print(f"  3. STM32 的 UART 波特率必须设为 {baud}")
    print("=" * 50)


if __name__ == "__main__":
    main()
