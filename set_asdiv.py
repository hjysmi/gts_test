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
 python set_asdiv.py 11
 
 # 切换到天线 3 (Config2, NV=0x22)
 python set_asdiv.py 22
 
 # 恢复默认配置
 python set_asdiv.py default
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

    # Map human-readable input to exact hex payload
    val_map = {
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
    target_val = val_map[args.value]

    print(f"[*] Initializing QUTS client: {args.client_name}...")
    client = QutsClient.QutsClient(args.client_name)
    devManager = client.getDeviceManager()

    print("[*] Finding connected DIAG-capable devices...")
    deviceList = devManager.getDevicesForService(DiagService.constants.DIAG_SERVICE_NAME)
    if not deviceList:
        print("[ERROR] No connected Qualcomm devices supporting DIAG service found!")
        print("Please check USB connection, device state, and Qualcomm USB drivers.")
        sys.exit(1)

    print(f"[+] Found {len(deviceList)} device(s). Selecting first device: {deviceList[0]}")
    target_device = deviceList[0]

    # Get DIAG handle
    print("[*] Retrieving DIAG protocol handle...")
    protList = devManager.getProtocolList(target_device)
    diagProtocolHandle = -1
    for prot in protList:
        if prot.protocolType == 0:  # DIAG
            diagProtocolHandle = prot.protocolHandle
            print(f"[+] Found DIAG Handle: {diagProtocolHandle} ({prot.description})")
            break

    if diagProtocolHandle == -1:
        print("[ERROR] No DIAG protocol handle found for the selected device.")
        sys.exit(1)

    # Create QXDM Service
    print("[*] Creating QXDM Service on target device...")
    qxdmService = QXDMService.QxdmService.Client(
        client.createService(QXDMService.constants.QXDM_SERVICE_NAME, target_device)
    )

    print("[*] Starting QXDM plugin on device...")
    if qxdmService.startQXDM(diagProtocolHandle) != 0:
        print("[ERROR] Failed to start QXDM diagnostic service.")
        sys.exit(1)
    print("[+] QXDM Service started successfully.")

    # Write EFS node
    print(f"[*] Writing EFS file: {args.efs_path}")
    print(f"[*] Setting value: {target_val}")
    cmd = f'RequestNVItemWrite {args.efs_path} {target_val}'.encode('utf-8')

    if qxdmService.sendCommand(cmd) == 0:
        print(f"[SUCCESS] EFS Write request sent: RequestNVItemWrite {args.efs_path} {target_val}")
        
        # Verify write by reading back
        print(f"[*] Verifying written value from EFS file: {args.efs_path}")
        read_cmd = f'RequestNVItemRead {args.efs_path}'.encode('utf-8')
        qxdmService.sendCommand(read_cmd)
        
        # Trigger offline/online resets to force Modem reload of EFS
        print("[*] Triggering Modem offline/online cycle to reload config...")
        qxdmService.sendCommand(b'mode lpm')
        time.sleep(1)
        qxdmService.sendCommand(b'mode online')
        print("[+] Cycle triggered (LPM -> ONLINE). Please wait a few seconds.")
    else:
        print("[ERROR] Failed to send write command to QXDM service.")

    # Clean up and close service
    print("[*] Destroying QXDM service...")
    qxdmService.destroyService()
    print("[*] Done!")

if __name__ == '__main__':
    main()
