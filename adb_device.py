#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Deep ADB Device Subsystem (adb_device.py)
Encapsulates Android device communication, connection guards, network mask
configuration, MTK logger broadcasts, and diagnostic fastboot bootmode management.
"""

import subprocess
import time
from enum import Enum
from typing import Optional, Union, Tuple, List, Dict


class FlowResult(tuple):
    """
    Result representing (success: bool, error_message: str).
    Evaluates to True if success is True, False otherwise.
    Supports tuple unpacking: success, err_msg = result
    """
    def __new__(cls, success: bool, error_message: str = ""):
        return super().__new__(cls, (bool(success), str(error_message)))

    @property
    def success(self) -> bool:
        return self[0]

    @property
    def error_message(self) -> str:
        return self[1]

    def __bool__(self):
        return self[0]

    def __repr__(self):
        return f"FlowResult(success={self[0]}, error_message={repr(self[1])})"


class NetworkMask(Enum):
    """
    Enum representing different allowed network type masks for telephony configuration.
    """
    LTE_ONLY = "01000001000000000000"         # 4G Only
    NR_ONLY = "10000000000000000000"          # 5G SA Only
    NR_LTE = "11000001000000000000"           # 5G/4G Automatic, 2G/3G disabled
    DEFAULT = "11001111101111111111"          # Factory Default: 5G/4G/3G/2G All enabled


def get_adb_devices() -> Dict[str, str]:
    """
    Execute 'adb devices' and return a dictionary of {serial: status}.
    """
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return {}
        lines = res.stdout.strip().splitlines()
        device_map = {}
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                device_map[parts[0]] = parts[1]
            elif len(parts) == 1:
                device_map[parts[0]] = "unknown"
        return device_map
    except Exception:
        return {}


def check_adb_device(target_serial: str) -> Tuple[bool, str]:
    """
    Verify if target_serial is present in 'adb devices' and in normal 'device' state.
    Returns (True, "") if valid, or (False, error_message) if mismatched/unavailable.
    """
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=False)
        if res.returncode != 0:
            return False, f"执行 'adb devices' 失败 (exit code {res.returncode}): {res.stderr.strip()}"
            
        lines = res.stdout.strip().splitlines()
        device_map = {}
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                device_map[parts[0]] = parts[1]
            elif len(parts) == 1:
                device_map[parts[0]] = "unknown"
                
        if not device_map:
            return False, "未检测到任何在线 ADB 设备。请检查 USB 数据线连接以及设备是否已开启开发者选项和 USB 调试。"
            
        if target_serial not in device_map:
            available = list(device_map.keys())
            return False, f"指定的设备序列号 '{target_serial}' 不在当前连接的 ADB 设备列表中！当前可用设备: {available}。请核对 --serial 参数。"
            
        status = device_map[target_serial]
        if status != "device":
            return False, f"目标设备 '{target_serial}' 状态异常 ({status})！若为 'unauthorized' 请在手机屏幕上确认允许 USB 调试；若为 'offline' 请重新插拔数据线。"
            
        return True, ""
    except FileNotFoundError:
        return False, "系统未找到 'adb' 命令，请确认 Android SDK Platform-Tools 已正确安装并配置到 PATH 环境变量中。"
    except Exception as e:
        return False, f"检查 ADB 设备列表时发生异常: {e}"


def get_fastboot_devices() -> List[str]:
    """
    Execute 'fastboot devices' and return a list of connected device serials.
    """
    try:
        res = subprocess.run(["fastboot", "devices"], capture_output=True, text=True, check=False)
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        devices = []
        for line in output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1].lower() == "fastboot":
                devices.append(parts[0])
            elif len(parts) == 1 and not line.startswith("<") and not line.startswith("?"):
                devices.append(parts[0])
        return devices
    except Exception as e:
        print(f"[ERROR] 执行 fastboot devices 异常: {e}")
        return []


def wait_for_fastboot_device(target_serial: str = "", timeout: int = 20) -> Tuple[bool, str]:
    """
    Poll 'fastboot devices' until a device is detected or timeout expires.
    Returns (True, serial) if found, (False, "") otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        devices = get_fastboot_devices()
        if devices:
            if target_serial and target_serial in devices:
                return True, target_serial
            return True, devices[0]
        time.sleep(1)
    return False, ""


def wait_for_adb_device(serial: str = "", timeout: int = 120) -> bool:
    """
    Wait for device to reboot into Android and reconnect to ADB, verifying sys.boot_completed.
    """
    wait_cmd = ["adb"]
    if serial:
        wait_cmd.extend(["-s", serial])
    wait_cmd.append("wait-for-device")

    print("[*] 等待 ADB 重新发现设备 (adb wait-for-device)...")
    try:
        subprocess.run(wait_cmd, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] 等待设备重新连接 ADB 超时 ({timeout}s)！")
        return False
    except Exception as e:
        print(f"[ERROR] 执行 adb wait-for-device 失败: {e}")
        return False

    print("[*] 正在等待系统完全启动 (sys.boot_completed)...")
    start_time = time.time()
    boot_completed = False
    while time.time() - start_time < 90:
        cmd = ["adb"]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(["shell", "getprop", "sys.boot_completed"])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.stdout.strip() == "1":
                boot_completed = True
                break
        except Exception:
            pass
        time.sleep(2)

    if boot_completed:
        print("[+] 系统开机启动完成 (sys.boot_completed=1)！")
    else:
        print("[WARNING] 等待 sys.boot_completed 超时，继续后续流程...")

    # 暂停数秒以便系统 USB 端口配置完全生效
    time.sleep(3)
    return True


class AdbDevice:
    """
    Deep encapsulation of Android Device interaction via ADB and Fastboot.
    """
    def __init__(self, serial: str):
        self.serial = str(serial).strip()

    def verify_connected(self) -> FlowResult:
        """
        Check if the target serial is present and authorized in 'adb devices'.
        """
        if not self.serial:
            return FlowResult(False, "设备序列号为空！")
        ok, err = check_adb_device(self.serial)
        return FlowResult(ok, err)

    def run_adb(self, args: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
        """
        Execute an ADB command against this specific device.
        """
        cmd = ["adb", "-s", self.serial] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)

    def get_prop(self, prop_name: str) -> str:
        """
        Get an Android system property value.
        """
        res = self.run_adb(["shell", "getprop", prop_name])
        return res.stdout.strip() if res.returncode == 0 else ""

    def ensure_diag_mode(self) -> FlowResult:
        """
        Verify that sys.usb.config contains 'diag'.
        If not, autonomously reboots to bootloader, configures bootmode qcom,
        reboots, and waits for system boot completion.
        """
        usb_config = self.get_prop("sys.usb.config")
        print(f"[*] 检查设备 USB 端口配置 (sys.usb.config): '{usb_config}'")
        
        if "diag" in usb_config.lower():
            print("[+] sys.usb.config 已包含 'diag'，无需切换。")
            return FlowResult(True, "")

        print("[*] sys.usb.config 不包含 'diag'，执行切换 bootmode qcom 流程...")
        
        # 1. adb reboot bootloader
        reboot_cmd = ["adb", "-s", self.serial, "reboot", "bootloader"]
        print(f"[*] 执行命令: {' '.join(reboot_cmd)}")
        subprocess.run(reboot_cmd, check=False)

        # 2. Check fastboot devices
        print("[*] 等待设备进入 bootloader 模式并执行 fastboot devices 检查...")
        fb_ok, fb_serial = wait_for_fastboot_device(self.serial, timeout=20)
        if not fb_ok:
            err_msg = "fastboot devices 未识别到设备，请确认设备是否处于 bootloader 状态，并请先安装驱动！"
            print(f"\n[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        print(f"[+] fastboot 成功识别到设备: {fb_serial}")

        # 3. fastboot oem config bootmode qcom
        target_fb = fb_serial if fb_serial else self.serial
        fb_config_cmd = ["fastboot", "-s", target_fb, "oem", "config", "bootmode", "qcom"]
        print(f"[*] 执行配置: {' '.join(fb_config_cmd)}")
        res_cfg = subprocess.run(fb_config_cmd, capture_output=True, text=True, check=False)
        out_cfg = ((res_cfg.stdout or "") + "\n" + (res_cfg.stderr or "")).strip()
        if out_cfg:
            print(f"  {out_cfg}")
        if res_cfg.returncode != 0:
            err_msg = f"fastboot oem config bootmode qcom 失败: {out_cfg}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        # 4. fastboot reboot
        fb_reboot_cmd = ["fastboot", "-s", target_fb, "reboot"]
        print(f"[*] 执行重启: {' '.join(fb_reboot_cmd)}")
        res_rb = subprocess.run(fb_reboot_cmd, capture_output=True, text=True, check=False)
        out_rb = ((res_rb.stdout or "") + "\n" + (res_rb.stderr or "")).strip()
        if out_rb:
            print(f"  {out_rb}")
        if res_rb.returncode != 0:
            err_msg = f"fastboot reboot 执行失败: {out_rb}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        # 5. Wait for device reconnect
        print("[*] 等待设备重启并重新连接 ADB...")
        if not wait_for_adb_device(self.serial, timeout=120):
            err_msg = "等待设备重启超时，ADB 未重新连接！"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        # 6. Verify sys.usb.config again
        final_usb_config = self.get_prop("sys.usb.config")
        print(f"[*] 重启后 sys.usb.config 值为: '{final_usb_config}'")
        if "diag" not in final_usb_config.lower():
            err_msg = f"设备已通过 fastboot 设置 bootmode qcom 并重启，但 sys.usb.config 仍不包含 'diag' (当前: '{final_usb_config}')。"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        print("[+] 成功开启 QCOM DIAG 端口配置！")
        return FlowResult(True, "")

    def set_network_mask(self, mask: Union[NetworkMask, str], sim_slot: int = 0) -> FlowResult:
        """
        Configure allowed network type mask via Android telephony cmd phone.
        """
        if sim_slot not in (0, 1):
            return FlowResult(False, f"无效卡槽索引: {sim_slot}，必须为 0 (SIM1) 或 1 (SIM2)")

        if isinstance(mask, str):
            try:
                mask_enum = NetworkMask[mask.upper()]
            except KeyError:
                return FlowResult(False, f"无效的网络掩码名称 '{mask}'")
        elif isinstance(mask, NetworkMask):
            mask_enum = mask
        else:
            return FlowResult(False, f"无效的掩码类型: {type(mask)}")

        cmd = [
            "shell", "cmd", "phone", "set-allowed-network-types-for-users",
            "-s", str(sim_slot), mask_enum.value
        ]
        print(f"[*] 正在为 SIM {sim_slot + 1} 配置网络掩码: {mask_enum.name} ({mask_enum.value})...")
        res = self.run_adb(cmd)
        if res.returncode == 0:
            print(f"[+] 成功设置 SIM {sim_slot + 1} 网络掩码为 {mask_enum.name}")
            return FlowResult(True, "")
        else:
            err = res.stderr.strip() or res.stdout.strip()
            err_msg = f"设置 SIM {sim_slot + 1} 网络掩码失败 (exit code {res.returncode}): {err}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

    def control_mtk_logger(self, action: str) -> FlowResult:
        """
        Control MTK logger via ADB broadcast ('stop', 'start', 'switch_usb').
        """
        commands = {
            "stop": [
                "shell", "am", "broadcast",
                "-a", "com.debug.loggerui.ADB_CMD",
                "-e", "cmd_name", "stop",
                "--ei", "cmd_target", "-1",
                "-n", "com.debug.loggerui/.framework.LogReceiver"
            ],
            "start": [
                "shell", "am", "broadcast",
                "-a", "com.debug.loggerui.ADB_CMD",
                "-e", "cmd_name", "start",
                "--ei", "cmd_target", "-1",
                "-n", "com.debug.loggerui/.framework.LogReceiver"
            ],
            "switch_usb": [
                "shell", "am", "broadcast",
                "-a", "com.debug.loggerui.ADB_CMD",
                "-e", "cmd_name", "switch_modem_log_mode",
                "--ei", "cmd_target", "1",
                "-n", "com.debug.loggerui/.framework.LogReceiver"
            ]
        }

        cmd_args = commands.get(action.lower())
        if not cmd_args:
            return FlowResult(False, f"未知的 MTK Logger 动作: '{action}'")

        print(f"[*] 执行 MTK Logger 广播命令: '{action}'...")
        res = self.run_adb(cmd_args)
        success = (res.returncode == 0)
        
        # 暂停 5 秒确保 Logger 状态完全生效
        print(f"[*] 等待 5 秒以确保 '{action}' 操作在底层生效...")
        time.sleep(5)
        
        if success:
            print(f"[+] MTK Logger '{action}' 执行成功。")
            return FlowResult(True, "")
        else:
            err = res.stderr.strip() or res.stdout.strip()
            err_msg = f"MTK Logger '{action}' 执行失败: {err}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
