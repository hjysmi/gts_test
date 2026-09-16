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
LOCAL_BASE_DIR = r"D:\share_179\0519\bank_prod\gts_test\LTE_Rx_select"

# Mode to local folder mapping
MODE_MAP = {
    'rx0': 'PCC Rx0 only',
    'rx1': 'PCC Rx1 only',
    'rx2': 'PCC Rx2 only',
    'rx3': 'PCC Rx3 only',
}

def main():
    """
    python .\set_lte_rx.py combine 该命令执行时，会在日志中显示发现的所有文件（例如 dc_offsets, hpue_ulca_enable 等等），并将它们逐一清空，使 ML1 彻底变为空白目录。
    python .\set_lte_rx.py rx0 执行该命令时，会首先清空 ML1 下的所有文件，然后自动把你本地的 D:\share_179\0519\bank_prod\gts_test\LTE_Rx_select\PCC Rx0 only\rx_select 文件写入到该目录下，并刷新 Modem。
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

    mode = args.mode.lower()

    # 1. Initialize QUTS client
    print(f"[*] Initializing QUTS client: {args.client_name}...")
    client = QutsClient.QutsClient(args.client_name)
    devManager = client.getDeviceManager()

    # 2. Search for DIAG-capable devices
    print("[*] Finding connected DIAG-capable devices...")
    deviceList = devManager.getDevicesForService(diag_constants.DIAG_SERVICE_NAME)
    if not deviceList:
        print("[ERROR] No connected Qualcomm devices supporting DIAG service found!")
        print("Please check USB connection, device state, and Qualcomm USB drivers.")
        sys.exit(1)

    target_device = deviceList[0]
    print(f"[+] Found device: {target_device}")

    # 3. Retrieve protocol handles
    print("[*] Retrieving protocol handles...")
    protList = devManager.getProtocolList(target_device)
    diagProtocolHandle = -1
    qmiProtocolHandle = -1
    for prot in protList:
        if prot.protocolType == 0:  # DIAG
            diagProtocolHandle = prot.protocolHandle
        elif prot.protocolType == 1:  # QMI
            qmiProtocolHandle = prot.protocolHandle

    if diagProtocolHandle == -1:
        print("[ERROR] No DIAG protocol handle found for the selected device.")
        sys.exit(1)
    if qmiProtocolHandle == -1:
        print("[WARNING] No QMI protocol handle found. Passing -1...")
        qmiProtocolHandle = -1

    # 4. Start QXDM Service (required backend)
    print("[*] Starting QXDM Service...")
    qxdm = qxdm_service.Client(client.createService(qxdm_constants.QXDM_SERVICE_NAME, target_device))
    if qxdm.startQXDM(diagProtocolHandle) != 0:
        print("[ERROR] Failed to start QXDM diagnostic service.")
        sys.exit(1)
    print("[+] QXDM Service started successfully.")

    # 5. Start DeviceConfig Service
    print("[*] Starting DeviceConfig Service...")
    dc = dc_service.Client(client.createService(dc_constants.DEVICE_CONFIG_SERVICE_NAME, target_device))
    try:
        dc.initializeServiceByProtocol(diagProtocolHandle, qmiProtocolHandle)
        print("[+] DeviceConfig Service initialized successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize DeviceConfig Service: {e}")
        qxdm.destroyService()
        sys.exit(1)

    # 6. Perform EFS Operations
    try:
        # A. Clean up all contents inside target EFS directory (ML1)
        print(f"[*] Checking and clearing all contents inside EFS directory: {EFS_DIR}")
        try:
            contents = dc.efsGetDirectoryContents(EFS_DIR, FileSystem.FS_PRIMARY)
            if contents:
                print(f"[+] Found {len(contents)} item(s) to clear in {EFS_DIR}.")
                for item in contents:
                    file_path = f"{EFS_DIR}/{item.name}"
                    print(f"  [-] Deleting: {file_path}")
                    try:
                        dc.efsDeleteFile(file_path, FileSystem.FS_PRIMARY)
                    except Exception as ex_del:
                        print(f"  [!] Failed to delete {file_path}: {ex_del}")
                print(f"[+] Successfully cleared all contents inside {EFS_DIR}.")
            else:
                print(f"[*] Directory {EFS_DIR} is already empty.")
        except Exception as e_get:
            print(f"[ERROR] Failed to read or clear EFS directory {EFS_DIR}: {e_get}")

        # B. If mode is not combine, upload the selected configuration
        if mode != 'combine':
            folder_name = MODE_MAP[mode]
            local_file_path = os.path.join(LOCAL_BASE_DIR, folder_name, "rx_select")
            
            if not os.path.exists(local_file_path):
                print(f"[ERROR] Local configuration file not found at: {local_file_path}")
                raise FileNotFoundError(f"Missing local config file for mode {mode}")

            print(f"[*] Reading local configuration file: {local_file_path}")
            with open(local_file_path, 'rb') as f:
                file_bytes = f.read()

            print(f"[*] Uploading configuration file to EFS: {EFS_FILE}")
            dc.efsPutFile(EFS_FILE, file_bytes, FileSystem.FS_PRIMARY)
            print(f"[SUCCESS] Successfully uploaded local rx_select config to EFS for mode: {mode}")
        else:
            print(f"[SUCCESS] Mode is 'combine'. Target EFS file {EFS_FILE} cleared (empty config).")

        # 7. Reset Modem (LPM -> ONLINE) to apply changes immediately
        print("[*] Triggering Modem offline/online cycle to reload config...")
        qxdm.sendCommand(b'mode lpm')
        time.sleep(1)
        qxdm.sendCommand(b'mode online')
        print("[+] Cycle triggered (LPM -> ONLINE). Please wait a few seconds.")

    except Exception as e:
        print(f"[ERROR] EFS operation failed: {e}")
    finally:
        # Clean up services
        print("[*] Cleaning up diagnostic services...")
        try:
            dc.destroyService()
        except:
            pass
        try:
            qxdm.destroyService()
        except:
            pass
        print("[*] Done!")

if __name__ == '__main__':
    main()
