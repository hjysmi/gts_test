#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qualcomm ASDiv Config Switch Tool via QUTS QXDM Service.
Writes value to /nv/item_files/mcs/trm/trm_ant_port_override_mode EFS node.
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
    import Common.ttypes
    import QXDMService.QxdmService
    import QXDMService.constants
    import QXDMService.ttypes
    import DiagService.constants
except ImportError as e:
    print(f"[ERROR] Failed to import Qualcomm QUTS libraries: {e}")
    print("Please make sure Qualcomm QUTS is properly installed and QUTS python support is available.")
    sys.exit(1)

# Map human-readable input to exact hex payload
VAL_MAP = {
    '0': '00',
    '00': '00',
    '1': '11',
    '11': '11',
    '2': '22',
    '22': '22',
    '3': '33',
    '33': '33',
    'default': 'FF',
    'FF': 'FF'
}

def init_quts_client(client_name="ASDivSwitchTool"):
    """
    初始化 QUTS 客户端 (Initialize QUTS Client)
    :param client_name: QUTS 客户端名称
    :return: (client, dev_manager) 元组
    """
    print(f"[*] Initializing QUTS client: {client_name}...")
    client = QutsClient.QutsClient(client_name)
    dev_manager = client.getDeviceManager()
    return client, dev_manager

def find_diag_device(dev_manager):
    """
    寻找支持 DIAG 服务的已连接 Qualcomm 设备 (Find connected Qualcomm devices supporting DIAG)
    :param dev_manager: QUTS DeviceManager 实例
    :return: 目标设备实例，若未找到则返回 None
    """
    print("[*] Finding connected DIAG-capable devices...")
    device_list = dev_manager.getDevicesForService(DiagService.constants.DIAG_SERVICE_NAME)
    if not device_list:
        print("[ERROR] No connected Qualcomm devices supporting DIAG service found!")
        print("Please check USB connection, device state, and Qualcomm USB drivers.")
        return None
    
    target_device = device_list[0]
    print(f"[+] Found {len(device_list)} device(s). Selecting first device: {target_device}")
    return target_device

def get_diag_handle(dev_manager, target_device):
    """
    获取目标设备的 DIAG 协议句柄 (Get DIAG protocol handle for target device)
    :param dev_manager: QUTS DeviceManager 实例
    :param target_device: 目标设备
    :return: DIAG 协议句柄，若未找到则返回 -1
    """
    print("[*] Retrieving DIAG protocol handle...")
    prot_list = dev_manager.getProtocolList(target_device)
    diag_protocol_handle = -1
    for prot in prot_list:
        if prot.protocolType == 0:  # DIAG
            diag_protocol_handle = prot.protocolHandle
            print(f"[+] Found DIAG Handle: {diag_protocol_handle} ({prot.description})")
            break
            
    if diag_protocol_handle == -1:
        print("[ERROR] No DIAG protocol handle found for the selected device.")
        
    return diag_protocol_handle

def start_qxdm_service(client, target_device, diag_protocol_handle):
    """
    在目标设备上创建并启动 QXDM 诊断服务 (Create and start QXDM diagnostic service on target device)
    :param client: QutsClient 实例
    :param target_device: 目标设备
    :param diag_protocol_handle: DIAG 协议句柄
    :return: qxdm_service 实例，若启动失败则返回 None
    """
    print("[*] Creating QXDM Service on target device...")
    qxdm_service = QXDMService.QxdmService.Client(
        client.createService(QXDMService.constants.QXDM_SERVICE_NAME, target_device)
    )

    print("[*] Starting QXDM plugin on device...")
    if qxdm_service.startQXDM(diag_protocol_handle) != 0:
        print("[ERROR] Failed to start QXDM diagnostic service.")
        return None
        
    print("[+] QXDM Service started successfully.")
    return qxdm_service

def write_efs_item(qxdm_service, efs_path, target_val):
    """
    向目标 EFS 文件写入指定值 (Write specific value to target EFS file)
    :param qxdm_service: QXDM 服务实例
    :param efs_path: EFS 节点路径
    :param target_val: 写入的十六进制值 (如 '11')
    :return: True 代表写入指令发送成功，False 代表失败
    """
    print(f"[*] Writing EFS file: {efs_path}")
    print(f"[*] Setting value: {target_val}")
    cmd = f'RequestNVItemWrite {efs_path} {target_val}'.encode('utf-8')
    
    if qxdm_service.sendCommand(cmd) == 0:
        print(f"[SUCCESS] EFS Write request sent: RequestNVItemWrite {efs_path} {target_val}")
        return True
    else:
        print("[ERROR] Failed to send write command to QXDM service.")
        return False

def verify_efs_item(qxdm_service, efs_path):
    """
    通过读取 EFS 文件来验证/触发刷新 (Verify written value by reading EFS file)
    :param qxdm_service: QXDM 服务实例
    :param efs_path: EFS 节点路径
    """
    print(f"[*] Verifying written value from EFS file: {efs_path}")
    read_cmd = f'RequestNVItemRead {efs_path}'.encode('utf-8')
    qxdm_service.sendCommand(read_cmd)

def reset_modem(qxdm_service):
    """
    触发 Modem 离线/在线循环以强制重新加载 EFS (Trigger Modem offline/online cycle to force EFS reload)
    :param qxdm_service: QXDM 服务实例
    """
    print("[*] Triggering Modem offline/online cycle to reload config...")
    qxdm_service.sendCommand(b'mode lpm')
    time.sleep(1)
    qxdm_service.sendCommand(b'mode online')
    print("[+] Cycle triggered (LPM -> ONLINE). Please wait a few seconds.")

def cleanup_service(qxdm_service):
    """
    注销并销毁 QXDM 服务 (Clean up and close QXDM service)
    :param qxdm_service: QXDM 服务实例
    """
    if qxdm_service:
        print("[*] Destroying QXDM service...")
        try:
            qxdm_service.destroyService()
        except Exception as e:
            print(f"[WARNING] Failed to destroy service: {e}")

def switch_asdiv_config(value, efs_path='/nv/item_files/mcs/trm/trm_ant_port_override_mode', client_name='ASDivSwitchTool'):
    """
    高层编排：执行完整的 ASDiv 天线切换、读取校验和 Modem 刷新 (High-level Orchestrator for ASDiv configuration switching)
    :param value: ASDiv 天线值 (例如 '00', '11', 'default')
    :param efs_path: EFS 文件节点路径
    :param client_name: QUTS 客户端名称
    :return: True 代表成功，False 代表发生任何错误
    """
    if value not in VAL_MAP:
        print(f"[ERROR] Invalid ASDiv value: {value}. Allowed values are: {list(VAL_MAP.keys())}")
        return False
        
    target_val = VAL_MAP[value]

    client = None
    qxdm_service = None
    try:
        # 1. 初始化 QUTS
        client, dev_manager = init_quts_client(client_name)
        
        # 2. 查找 DIAG 设备
        target_device = find_diag_device(dev_manager)
        if not target_device:
            return False
            
        # 3. 获取协议句柄
        diag_handle = get_diag_handle(dev_manager, target_device)
        if diag_handle == -1:
            return False
            
        # 4. 创建并启动 QXDM 诊断服务
        qxdm_service = start_qxdm_service(client, target_device, diag_handle)
        if not qxdm_service:
            return False
            
        # 5. 写入 EFS 值并进行后续处理
        if write_efs_item(qxdm_service, efs_path, target_val):
            verify_efs_item(qxdm_service, efs_path)
            reset_modem(qxdm_service)
            return True
        else:
            return False
            
    except Exception as e:
        print(f"[ERROR] Exception occurred during ASDiv switch: {e}")
        return False
    finally:
        if qxdm_service:
            cleanup_service(qxdm_service)

def main():
    """
      选项速查：
   * 00 / 0: Config0 (ANT1)
   * 11 / 1: Config1 (ANT2)
   * 22 / 2: Config2 (ANT3)
   * 33 / 3: Config3 (ANT4)
   * FF / default: 恢复默认天线 (Default)

  运行示例：

 # 切换到天线 2 (Config1, NV=0x11)
 python efs.py 11
 
 # 切换到天线 3 (Config2, NV=0x22)
 python efs.py 22
 
 # 恢复默认配置
 python efs.py default
    """
    parser = argparse.ArgumentParser(description="Qualcomm ASDiv Config Switching CLI Tool")
    parser.add_argument(
        'value', 
        choices=['00', '11', '22', '33', 'FF', '0', '1', '2', '3', 'default'],
        help="ASDiv path value to write. "
             "Options: 00 (Config0/ANT1), 11 (Config1/ANT2), 22 (Config2/ANT3), 33 (Config3/ANT4), FF (Default)"
    )
    parser.add_argument(
        '--efs-path', 
        default='/nv/item_files/mcs/trm/trm_ant_port_override_mode',
        help="EFS file path to modify"
    )
    parser.add_argument(
        '--client-name', 
        default='ASDivSwitchTool',
        help="QUTS Client name"
    )
    args = parser.parse_args()

    success = switch_asdiv_config(
        value=args.value,
        efs_path=args.efs_path,
        client_name=args.client_name
    )
    
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()