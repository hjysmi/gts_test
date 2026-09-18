#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qualcomm LTE Rx Path Selection Automation Tool.
Automates the EFS Explorer workflow for LTE Rx path selection via QUTS.
"""

import warnings
# Ignore QUTS internal SyntaxWarnings caused by backslashes in docstrings
warnings.filterwarnings("ignore", category=SyntaxWarning)

import sys
import os
import time
import argparse

# Define Qualcomm QUTS Support Python Paths
QUTS_PATHS = [
    r'C:\Program Files\Qualcomm\QUTS\Support\python',
    r'C:\Program Files (x86)\Qualcomm\QUTS\Support\python',
    '/opt/qcom/QUTS/Support/python'
]

# Append paths to sys.path
for path in QUTS_PATHS:
    if os.path.exists(path) and path not in sys.path:
        sys.path.append(path)

try:
    import QutsClient
    import DiagService.constants as diag_constants
    import DeviceConfigService.DeviceConfigService as dc_service
    import DeviceConfigService.constants as dc_constants
    from DeviceConfigService.ttypes import FileSystem, EfsType
    import QXDMService.QxdmService as qxdm_service
    import QXDMService.constants as qxdm_constants
except ImportError as e:
    print(f"[ERROR] Failed to import Qualcomm QUTS libraries: {e}")
    print("Please make sure Qualcomm QUTS is properly installed and QUTS python support is available.")
    sys.exit(1)

# Define constants
EFS_DIR = "/nv/item_files/modem/lte/ML1"
EFS_FILE = "/nv/item_files/modem/lte/ML1/rx_select"

# Local directories
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    LOCAL_BASE_DIR = os.path.join(SCRIPT_DIR, "LTE_Rx_select")
except NameError:
    LOCAL_BASE_DIR = r"D:\share_179\0519\bank_prod\gts_test\LTE_Rx_select"

# Mode to local folder mapping
MODE_MAP = {
    'rx0': 'PCC Rx0 only',
    'rx1': 'PCC Rx1 only',
    'rx2': 'PCC Rx2 only',
    'rx3': 'PCC Rx3 only',
}


def init_quts_client(client_name="LteRxSwitchTool"):
    """
    初始化 QUTS 客户端并获取 DeviceManager
    (Initialize QUTS client and get DeviceManager)
    :param client_name: 客户端名称 (Client name)
    :return: (client, dev_manager) 元组 (tuple)
    """
    print(f"[*] Initializing QUTS client: {client_name}...")
    client = QutsClient.QutsClient(client_name)
    dev_manager = client.getDeviceManager()
    return client, dev_manager


def find_diag_device(dev_manager):
    """
    寻找已连接并支持 DIAG 服务的 Qualcomm 设备
    (Find connected Qualcomm devices supporting DIAG service)
    :param dev_manager: DeviceManager 实例
    :return: 目标设备实例，若未找到则返回 None
    """
    print("[*] Finding connected DIAG-capable devices...")
    device_list = dev_manager.getDevicesForService(diag_constants.DIAG_SERVICE_NAME)
    if not device_list:
        print("[ERROR] No connected Qualcomm devices supporting DIAG service found!")
        print("Please check USB connection, device state, and Qualcomm USB drivers.")
        return None
    target_device = device_list[0]
    print(f"[+] Found device: {target_device}")
    return target_device


def get_protocol_handles(dev_manager, target_device):
    """
    获取 DIAG 和 QMI 协议句柄
    (Get DIAG and QMI protocol handles)
    :param dev_manager: DeviceManager 实例
    :param target_device: 目标设备
    :return: (diag_handle, qmi_handle) 元组
    """
    print("[*] Retrieving protocol handles...")
    prot_list = dev_manager.getProtocolList(target_device)
    diag_handle = -1
    qmi_handle = -1
    for prot in prot_list:
        if prot.protocolType == 0:  # DIAG
            diag_handle = prot.protocolHandle
        elif prot.protocolType == 1:  # QMI
            qmi_handle = prot.protocolHandle

    if diag_handle == -1:
        print("[ERROR] No DIAG protocol handle found for the selected device.")
    return diag_handle, qmi_handle


def start_qxdm_service(client, target_device, diag_handle):
    """
    创建并启动 QXDM 诊断服务
    (Create and start QXDM diagnostic service)
    :param client: QutsClient 实例
    :param target_device: 目标设备
    :param diag_handle: DIAG 协议句柄
    :return: QxdmService 客户端实例，若失败则返回 None
    """
    print("[*] Starting QXDM Service...")
    try:
        qxdm = qxdm_service.Client(client.createService(qxdm_constants.QXDM_SERVICE_NAME, target_device))
        if qxdm.startQXDM(diag_handle) != 0:
            print("[ERROR] Failed to start QXDM diagnostic service.")
            return None
        print("[+] QXDM Service started successfully.")
        return qxdm
    except Exception as e:
        print(f"[ERROR] Exception during QXDM starting: {e}")
        return None


def start_device_config_service(client, target_device, diag_handle, qmi_handle):
    """
    创建并启动 DeviceConfig 诊断服务
    (Create and start DeviceConfig service)
    :param client: QutsClient 实例
    :param target_device: 目标设备
    :param diag_handle: DIAG 协议句柄
    :param qmi_handle: QMI 协议句柄
    :return: DeviceConfigService 客户端实例，若失败则返回 None
    """
    print("[*] Starting DeviceConfig Service...")
    try:
        dc = dc_service.Client(client.createService(dc_constants.DEVICE_CONFIG_SERVICE_NAME, target_device))
        dc.initializeServiceByProtocol(diag_handle, qmi_handle)
        print("[+] DeviceConfig Service initialized successfully.")
        return dc
    except Exception as e:
        print(f"[ERROR] Failed to initialize DeviceConfig Service: {e}")
        return None


def clear_efs_directory(dc_client, dir_path=EFS_DIR):
    """
    清空指定的 EFS 目录下所有文件
    (Clear all contents inside EFS directory)
    :param dc_client: 已初始化的 DeviceConfig 客户端实例
    :param dir_path: EFS 目录路径
    :return: True 代表操作成功或目录已空，False 代表失败
    """
    print(f"[*] Checking and clearing all contents inside EFS directory: {dir_path}")
    try:
        contents = dc_client.efsGetDirectoryContents(dir_path, FileSystem.FS_PRIMARY)
        if contents:
            print(f"[+] Found {len(contents)} item(s) to clear in {dir_path}.")
            for item in contents:
                file_path = f"{dir_path}/{item.name}"
                print(f"  [-] Deleting: {file_path}")
                try:
                    dc_client.efsDeleteFile(file_path, FileSystem.FS_PRIMARY)
                except Exception as ex_del:
                    print(f"  [!] Failed to delete {file_path}: {ex_del}")
            print(f"[+] Successfully cleared all contents inside {dir_path}.")
        else:
            print(f"[*] Directory {dir_path} is already empty.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to read or clear EFS directory {dir_path}: {e}")
        return False


def upload_local_file_to_efs(dc_client, local_path, target_efs_path=EFS_FILE):
    """
    读取本地文件并写入到设备 target_efs_path
    (Upload local file to EFS)
    :param dc_client: 已初始化的 DeviceConfig 客户端实例
    :param local_path: 本地文件路径
    :param target_efs_path: 设备目标 EFS 文件路径
    :return: True 代表写入成功，False 代表失败
    """
    if not os.path.exists(local_path):
        print(f"[ERROR] Local file not found at: {local_path}")
        return False

    print(f"[*] Reading local configuration file: {local_path}")
    try:
        with open(local_path, 'rb') as f:
            file_bytes = f.read()

        print(f"[*] Uploading configuration file to EFS: {target_efs_path}")
        dc_client.efsPutFile(target_efs_path, file_bytes, FileSystem.FS_PRIMARY)
        print(f"[+] Successfully uploaded local config to EFS path: {target_efs_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to upload local file to EFS: {e}")
        return False


def reset_modem(qxdm_client):
    """
    触发 Modem LPM -> ONLINE 离在线循环以强制重新加载配置
    (Trigger Modem offline/online cycle to force EFS reload)
    :param qxdm_client: QxdmService 实例
    """
    print("[*] Triggering Modem offline/online cycle to reload config...")
    try:
        qxdm_client.sendCommand(b'mode lpm')
        time.sleep(1)
        qxdm_client.sendCommand(b'mode online')
        print("[+] Cycle triggered (LPM -> ONLINE). Please wait a few seconds.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send modem commands: {e}")
        return False


def switch_lte_rx(mode, client_name="LteRxSwitchTool"):
    """
    高层编排：执行完整的 LTE Rx 路径选择自动化切换
    (High-level Orchestrator for LTE Rx path selection switching)
    :param mode: 选择的模式: 'combine', 'rx0', 'rx1', 'rx2', 'rx3'
    :param client_name: QUTS 客户端名称
    :return: True 代表操作成功，False 代表失败
    """
    mode = mode.lower()
    if mode not in ['combine', 'rx0', 'rx1', 'rx2', 'rx3']:
        print(f"[ERROR] Invalid Rx mode: '{mode}'. Allowed modes are 'combine', 'rx0', 'rx1', 'rx2', 'rx3'.")
        return False

    client = None
    qxdm = None
    dc = None
    success = False

    try:
        # 1. 初始化 QUTS 客户端
        client, dev_manager = init_quts_client(client_name)

        # 2. 寻找 DIAG 设备
        target_device = find_diag_device(dev_manager)
        if not target_device:
            return False

        # 3. 获取协议句柄
        diag_handle, qmi_handle = get_protocol_handles(dev_manager, target_device)
        if diag_handle == -1:
            return False

        # 4. 启动 QXDM 诊断服务
        qxdm = start_qxdm_service(client, target_device, diag_handle)
        if not qxdm:
            return False

        # 5. 启动 DeviceConfig 诊断服务
        dc = start_device_config_service(client, target_device, diag_handle, qmi_handle)
        if not dc:
            return False

        # 6. 清空 EFS 目录
        if not clear_efs_directory(dc, EFS_DIR):
            return False

        # 7. 如果不是 combine 模式，上传选定的 rx_select 配置文件
        if mode != 'combine':
            folder_name = MODE_MAP[mode]
            local_file_path = os.path.join(LOCAL_BASE_DIR, folder_name, "rx_select")
            if not upload_local_file_to_efs(dc, local_file_path, EFS_FILE):
                return False
            print(f"[SUCCESS] Successfully completed EFS file writing for mode: {mode}")
        else:
            print(f"[SUCCESS] Mode is 'combine'. Target EFS directory {EFS_DIR} cleared (empty config).")

        # 8. 重启 Modem
        if reset_modem(qxdm):
            success = True

    except Exception as e:
        print(f"[ERROR] EFS operation failed with exception: {e}")
    finally:
        # 清理资源
        print("[*] Cleaning up diagnostic services...")
        if dc:
            try:
                dc.destroyService()
            except Exception as e_dc:
                print(f"[WARNING] Failed to destroy DeviceConfig Service: {e_dc}")
        if qxdm:
            try:
                qxdm.destroyService()
            except Exception as e_qxdm:
                print(f"[WARNING] Failed to destroy QXDM Service: {e_qxdm}")
        print("[*] Done!")

    return success


def main():
    r"""
    命令行运行主入口。
    python .\qc_lte_rx.py combine 该命令执行时，会在日志中显示发现的所有文件（例如 dc_offsets, hpue_ulca_enable 等等），并将它们逐一清空，使 ML1 彻底变为空白目录。
    python .\qc_lte_rx.py rx0 执行该命令时，会首先清空 ML1 下的所有文件，然后自动把你本地 D:\share_179\0519\bank_prod\gts_test\LTE_Rx_select\PCC Rx0 only\rx_select 文件写入到该目录下，并刷新 Modem。
    """
    parser = argparse.ArgumentParser(description="Qualcomm LTE Rx Path Selection Automation Tool")
    parser.add_argument(
        'mode',
        choices=['combine', 'rx0', 'rx1', 'rx2', 'rx3'],
        help="Rx selection mode: 'combine' (clears configuration), 'rx0', 'rx1', 'rx2', 'rx3'"
    )
    parser.add_argument(
        '--client-name',
        default='LteRxSwitchTool',
        help="QUTS Client name"
    )
    args = parser.parse_args()

    success = switch_lte_rx(mode=args.mode, client_name=args.client_name)
    if not success:
        sys.exit(1)


if __name__ == '__main__':
    main()
