#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Deep Qualcomm Modem Subsystem (qc_modem.py)
Consolidates QUTS Client, DeviceConfigService, and QxdmService into a single deep
QualcommModemSession module. Eliminates lifecycle churn, provides single-point serial
device locking, and performs in-memory EFS byte uploads without temporary disk files.
"""

import sys
import os
import json
import time
from typing import Optional, Tuple, Dict, Any

from adb_device import FlowResult

# 1. Setup QUTS Python Path
QUTS_PYTHON_PATH = r'C:\Program Files\Qualcomm\QUTS\Support\Python'
if os.path.exists(QUTS_PYTHON_PATH) and QUTS_PYTHON_PATH not in sys.path:
    sys.path.append(QUTS_PYTHON_PATH)

# 2. Thrift compatibility patch
try:
    import thrift.Thrift as _t
    if not hasattr(_t, 'TType'):
        class _MockTType:
            STOP = 0
            VOID = 1
            BOOL = 2
            BYTE = 3
            I08 = 3
            DOUBLE = 4
            I16 = 6
            I32 = 8
            I64 = 10
            STRING = 11
            UTF7 = 11
            STRUCT = 12
            MAP = 13
            SET = 14
            LIST = 15
            UTF8 = 16
            UTF16 = 17
        _t.TType = _MockTType
except ImportError:
    pass

try:
    import thrift.compat
    thrift.compat.str_to_binary = lambda s: s if isinstance(s, bytes) else bytes(s, 'utf8')
except Exception:
    pass

try:
    import QutsClient
    import DeviceConfigService.DeviceConfigService as dc_service
    import DeviceConfigService.constants as dc_constants
    from DeviceConfigService.ttypes import FileSystem, NvReturns, NvReturnFlags
    try:
        import QXDMService.QxdmService as qxdm_service
        import QXDMService.constants as qxdm_constants
    except ImportError:
        import QxdmService.QxdmService as qxdm_service
        import QxdmService.constants as qxdm_constants
except ImportError as e:
    # Allows module to be imported and inspected even if QUTS isn't locally installed
    QutsClient = None
    dc_service = None
    dc_constants = None
    FileSystem = None
    NvReturns = None
    NvReturnFlags = None
    qxdm_service = None
    qxdm_constants = None

if FileSystem is None:
    class _FallbackFS:
        FS_PRIMARY = 0
    FileSystem = _FallbackFS

if NvReturnFlags is None:
    class _FallbackNvReturnFlags:
        BINARY_PAYLOAD = 1
        PARSED_TEXT = 2
        JSON_TEXT = 3
        VALUE_LIST = 4
    NvReturnFlags = _FallbackNvReturnFlags

if NvReturns is None:
    class _FallbackNvReturns:
        def __init__(self, flags=0, fieldQueries=None):
            self.flags = flags
            self.fieldQueries = fieldQueries or []
    NvReturns = _FallbackNvReturns


# Standard NV Constants
NV_73971_JSON = json.dumps({
    "Version": 1,
    "Master_NV_1X": "DO NOT CARE",
    "Master_NV_HDR": "DO NOT CARE",
    "Master_NV_GSM": "ENABLE",
    "Master_NV_WCDMA": "ENABLE",
    "Master_NV_TDSCDMA": "DO NOT CARE",
    "Master_NV_LTE": "ENABLE",
    "Master_NV_NR": "ENABLE"
})

TX_NV73841_MAP = {
    "tx0": 0,    # TX0 (0x00)
    "0": 0,
    "tx1": 17,   # TX1 (0x11)
    "1": 17,
    "tx2": 34,   # TX2 (0x22)
    "2": 34,
    "tx3": 51,   # TX3 (0x33)
    "3": 51
}

# EFS Paths and Rx Mode Byte Masks (Qualcomm 80-N5220-2)
EFS_DIR_ML1 = "/nv/item_files/modem/lte/ML1"
EFS_FILE_RX_SELECT = "/nv/item_files/modem/lte/ML1/rx_select"

RX_MODE_BYTES_MAP = {
    'rx0': b'\x01',
    'rx1': b'\x02',
    'rx2': b'\x04',
    'rx3': b'\x08',
}


class QualcommModemSession:
    """
    Deep context manager for all Qualcomm Modem diagnostics, NV item manipulation,
    EFS diversity switching, and XQCN restore operations.
    """
    def __init__(self, target_serial: str, client_name: str = "QualcommModemSession"):
        self.target_serial = str(target_serial).strip()
        self.client_name = client_name
        self.quts_client = None
        self.dev_manager = None
        self.device_handle = None
        self.diag_handle = -1
        self.qmi_handle = -1
        self.dc_client = None
        self.qxdm_client = None
        self._is_open = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        """
        Initialize QUTS client, match device handle by target_serial, and initialize services.
        """
        if self._is_open:
            return

        if QutsClient is None:
            raise RuntimeError("Qualcomm QUTS Python 支持库未安装或未加载！请确认 QUTS 已安装并包含 Python 支持。")

        print(f"\n[*] 正在建立与 QUTS 守护服务的连接 (Client Name: {self.client_name})...")
        self.quts_client = QutsClient.QutsClient(self.client_name)
        self.dev_manager = self.quts_client.getDeviceManager()

        # 1. 精准锁定目标设备句柄
        device_list = self.dev_manager.getDeviceList()
        if not device_list:
            raise RuntimeError("QUTS 未检测到任何已连接的 Qualcomm 诊断设备！请确认 USB 驱动与 DIAG 端口状态。")

        print("[*] 正在 QUTS 设备拓扑中匹配目标序列号...")
        matched_handle = None
        available_devices = []

        for dev in device_list:
            adb_sn = getattr(dev, "adbSerialNumber", "")
            serial_sn = getattr(dev, "serialNumber", "")
            dev_hnd = getattr(dev, "deviceHandle", None)
            available_devices.append(f"{adb_sn or serial_sn} (Handle: {dev_hnd})")
            
            if self.target_serial in (adb_sn, serial_sn) or (dev_hnd and str(dev_hnd) == self.target_serial):
                matched_handle = dev_hnd
                break

        if matched_handle is None:
            # 兼容单设备快速匹配
            if len(device_list) == 1 and not self.target_serial:
                matched_handle = device_list[0].deviceHandle
            else:
                raise RuntimeError(
                    f"未在 QUTS 设备列表中找到序列号为 '{self.target_serial}' 的设备！"
                    f"当前 QUTS 已发现设备: {available_devices}"
                )

        self.device_handle = matched_handle
        print(f"[+] 成功锁定目标 QUTS 设备句柄: {self.device_handle} (Serial: {self.target_serial})")

        # 2. 检查并获取协议句柄 (DIAG / QMI)
        prot_list = self.dev_manager.getProtocolList(self.device_handle)
        for prot in prot_list:
            if prot.protocolType == 0:    # DIAG
                self.diag_handle = prot.protocolHandle
            elif prot.protocolType == 1:  # QMI
                self.qmi_handle = prot.protocolHandle

        # 3. 初始化并缓存 DeviceConfigService
        dc_svc_name = dc_constants.DEVICE_CONFIG_SERVICE_NAME
        supported_dc = self.dev_manager.getDevicesForService(dc_svc_name)
        if self.device_handle in supported_dc:
            print("[*] 正在初始化 DeviceConfigService 服务...")
            self.dc_client = dc_service.Client(
                self.quts_client.createService(dc_svc_name, self.device_handle)
            )
            if self.diag_handle != -1 and self.qmi_handle != -1:
                self.dc_client.initializeServiceByProtocol(self.diag_handle, self.qmi_handle)
            else:
                self.dc_client.initializeService()
            print("[+] DeviceConfigService 初始化完成。")

        # 4. 初始化并缓存 QxdmService (若支持 DIAG 协议)
        if self.diag_handle != -1:
            qxdm_svc_name = qxdm_constants.QXDM_SERVICE_NAME
            supported_qxdm = self.dev_manager.getDevicesForService(qxdm_svc_name)
            if self.device_handle in supported_qxdm:
                print("[*] 正在启动 QxdmService 诊断协议服务...")
                self.qxdm_client = qxdm_service.Client(
                    self.quts_client.createService(qxdm_svc_name, self.device_handle)
                )
                if self.qxdm_client.startQXDM(self.diag_handle) == 0:
                    print("[+] QxdmService 启动完成。")
                else:
                    print("[WARNING] startQXDM 返回非零，可能影响部分底层诊断指令。")

        self._is_open = True

    def close(self):
        """
        Clean up all active services and disconnect QUTS client cleanly.
        """
        if not self._is_open:
            return

        print("\n[*] 正在释放 QUTS 诊断通道与服务句柄...")
        if self.dc_client:
            try:
                self.dc_client.destroyService()
            except Exception as e:
                print(f"[WARNING] 注销 DeviceConfigService 异常: {e}")
            self.dc_client = None

        if self.qxdm_client:
            try:
                self.qxdm_client.destroyService()
            except Exception as e:
                print(f"[WARNING] 注销 QxdmService 异常: {e}")
            self.qxdm_client = None

        self.quts_client = None
        self._is_open = False
        print("[+] QUTS 客户端通道已安全关闭释放。")

    def write_nv(self, nv_id: str, nv_value: str, sub_id: int = -1) -> FlowResult:
        """
        Write a specific NV item value to the connected device.
        """
        if not self.dc_client:
            return FlowResult(False, "DeviceConfigService 未就绪，无法写入 NV！")

        print(f"[*] 写入 NV {nv_id} -> {nv_value} (sub_id={sub_id})...")
        err_code = self.dc_client.nvSetItem(str(nv_id), str(nv_value), sub_id)
        if err_code == 0:
            print(f"[+] NV {nv_id} 写入成功。")
            return FlowResult(True, "")
        else:
            err_detail = self.dc_client.getLastError()
            err_msg = f"NV {nv_id} 写入失败 (code={err_code}): {err_detail}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

    def query_nv(self, nv_id: str, sub_id: int = -1) -> Tuple[bool, str]:
        """
        Read a specific NV item value from the connected device.
        """
        if not self.dc_client:
            return False, "DeviceConfigService 未就绪"

        print(f"[*] 查询 NV {nv_id} 当前值...")
        try:
            return_config = NvReturns(flags=NvReturnFlags.JSON_TEXT)
            res = self.dc_client.nvReadItem(str(nv_id), sub_id, 0, return_config)
            if res.errorCode == 0:
                val = res.parsedJson if res.parsedJson is not None else (res.parsedText if res.parsedText is not None else str(res.payload or ""))
                print(f"[+] NV {nv_id} 查询结果: {val}")
                return True, str(val)
            else:
                err_detail = self.dc_client.getLastError() if hasattr(self.dc_client, 'getLastError') else f"Error code {res.errorCode}"
                print(f"[WARNING] NV {nv_id} 查询返回失败: {err_detail}")
                return False, str(err_detail)
        except Exception as e:
            err_msg = f"NV {nv_id} 查询异常: {e}"
            print(f"[WARNING] {err_msg}")
            return False, err_msg

    def set_antenna_tx(self, tx_target: str) -> FlowResult:
        """
        Set Qualcomm TX antenna forcing mode by writing NV 73971 and NV 73841.
        """
        tx_key = str(tx_target).lower()
        if tx_key not in TX_NV73841_MAP:
            return FlowResult(False, f"未知的 TX 天线目标 '{tx_target}'，支持选项: {list(TX_NV73841_MAP.keys())}")

        nv73841_val = TX_NV73841_MAP[tx_key]

        # 1. 写入并查询 NV 73971 (ASDiv bands master)
        print("\n[*] 配置 NV 73971 (ASDiv bands master)...")
        res_73971 = self.write_nv("73971", NV_73971_JSON)
        if not res_73971:
            return FlowResult(False, f"Step 1a 配置 NV 73971 失败: {res_73971.error_message}")
        self.query_nv("73971")

        # 2. 写入并查询 NV 73841 (TX Antenna Switch)
        print(f"\n[*] 配置 NV 73841 为 TX 目标 '{tx_target.upper()}' (写入值: {nv73841_val})...")
        res_73841 = self.write_nv("73841", str(nv73841_val))
        if not res_73841:
            return FlowResult(False, f"Step 1b 配置 NV 73841 失败: {res_73841.error_message}")
        self.query_nv("73841")

        return FlowResult(True, "")

    def switch_lte_rx(self, mode: str) -> FlowResult:
        """
        Configure LTE RX path selection override:
        - Clears /nv/item_files/modem/lte/ML1
        - In-memory upload of rx_select byte payload (no disk I/O)
        - Triggers Modem LPM -> ONLINE cycle
        """
        mode = mode.lower()
        if mode not in ['combine_4rx', 'rx0', 'rx1', 'rx2', 'rx3']:
            return FlowResult(False, f"无效的 LTE RX 模式: '{mode}'")

        if not self.dc_client:
            return FlowResult(False, "DeviceConfigService 未就绪，无法修改 EFS！")

        print(f"\n[*] 正在配置 LTE RX 分集路径模式: '{mode}'...")

        # 1. 清空 EFS 目录
        print(f"[*] 检查并清空 EFS 目录: {EFS_DIR_ML1}...")
        try:
            contents = self.dc_client.efsGetDirectoryContents(EFS_DIR_ML1, FileSystem.FS_PRIMARY)
            if contents:
                print(f"[+] 发现 {len(contents)} 个旧文件，正在清空...")
                for item in contents:
                    file_path = f"{EFS_DIR_ML1}/{item.name}"
                    try:
                        self.dc_client.efsDeleteFile(file_path, FileSystem.FS_PRIMARY)
                    except Exception as ex_del:
                        print(f"  [!] 删除旧文件失败: {file_path}: {ex_del}")
                print(f"[+] 已清空 EFS 目录 {EFS_DIR_ML1}。")
            else:
                print(f"[*] 目录 {EFS_DIR_ML1} 已处于空状态。")
        except Exception as e:
            return FlowResult(False, f"清空 EFS 目录 {EFS_DIR_ML1} 失败: {e}")

        # 2. 如果不是 combine_4rx，直接通过内存下发 rx_select 字节
        if mode != 'combine_4rx':
            rx_byte = RX_MODE_BYTES_MAP.get(mode)
            if not rx_byte:
                return FlowResult(False, f"模式 '{mode}' 没有定义对应的字节掩码！")

            print(f"[*] 正在通过内存字节流直接写入 EFS 节点: {EFS_FILE_RX_SELECT} (Payload: 0x{rx_byte.hex()})...")
            try:
                self.dc_client.efsPutFile(EFS_FILE_RX_SELECT, rx_byte, FileSystem.FS_PRIMARY)
                print(f"[+] EFS 节点 {EFS_FILE_RX_SELECT} 写入完成。")
            except Exception as e:
                return FlowResult(False, f"向 EFS 写入 {EFS_FILE_RX_SELECT} 失败: {e}")
        else:
            print(f"[+] 模式为 'combine_4rx'，已通过清空 {EFS_DIR_ML1} 恢复全天线接收配置。")

        # 3. 触发 Modem 离线/在线周期
        if self.qxdm_client:
            print("[*] 正在触发 Modem LPM -> ONLINE 重载生命周期...")
            try:
                self.qxdm_client.sendCommand(b'mode lpm')
                time.sleep(1)
                self.qxdm_client.sendCommand(b'mode online')
                print("[+] Modem 离在线刷新指令已下发。")
            except Exception as e:
                print(f"[WARNING] 下发 mode lpm/online 发生异常: {e}")

        return FlowResult(True, "")

    def restore_xqcn(
        self,
        xqcn_path: str,
        spc: str = "000000",
        allow_esn_mismatch: bool = True,
        reset_upon_completion: bool = False,
        reset_timeout_ms: int = 15000,
        filter_xml: str = ""
    ) -> FlowResult:
        """
        Restore QCN / XQCN calibration and NV backup via DeviceConfigService.
        """
        if not self.dc_client:
            return FlowResult(False, "DeviceConfigService 未就绪，无法导入 XQCN！")

        abs_path = os.path.abspath(xqcn_path)
        if not os.path.exists(abs_path):
            return FlowResult(False, f"指定的备份文件不存在: '{abs_path}'")

        print(f"\n[*] 正在加载并读取备份文件: {abs_path}...")
        try:
            with open(abs_path, 'rb') as f:
                xqcn_data = f.read()
        except Exception as e:
            return FlowResult(False, f"读取 XQCN 备份文件失败: {e}")

        print(f"[*] 正在通过 DeviceConfigService 恢复备份 (大小: {len(xqcn_data)} 字节)...")
        print(f" - 允许 ESN/IMEI 错配: {allow_esn_mismatch}")
        print(f" - QUTS 自动重启设备: {reset_upon_completion}")

        try:
            err_code = self.dc_client.restoreFromXqcn(
                xqcn_data,
                str(spc),
                bool(allow_esn_mismatch),
                bool(reset_upon_completion),
                int(reset_timeout_ms),
                str(filter_xml)
            )
        except Exception as e:
            err_msg = f"DeviceConfigService restoreFromXqcn 调用异常: {e}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

        if err_code == 0:
            print("[+] QCN/XQCN 恢复指令成功下发并写入完毕！")
            return FlowResult(True, "")
        else:
            err_detail = self.dc_client.getLastError() if hasattr(self.dc_client, 'getLastError') else f"Error code {err_code}"
            # 容错处理：若因 QUTS 等待设备重启超时，但数据实际已写入完毕且设备正在重启
            if "Could not Restart Device within the timeout period" in str(err_detail):
                print("[+] QCN/XQCN 数据已写入完毕，设备已安排重启 (已忽略 QUTS 端口重连超时提示)。")
                return FlowResult(True, "")

            err_msg = f"QCN/XQCN 恢复失败 (code={err_code}): {err_detail}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
