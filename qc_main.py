import warnings
# Ignore QUTS internal SyntaxWarnings caused by backslashes in docstrings
warnings.filterwarnings("ignore", category=SyntaxWarning)

import os
import sys
import argparse
import json
import subprocess
import time

# Import required local scripts
import qc_restore_xqcn
import qc_nv
import qc_lte_rx
import android_network_manager

# Allowed values for validation
ALLOWED_RATS = ["LTE", "LTE_ONLY", "NR", "NR_ONLY"]
ALLOWED_TX_VALUES = ["tx0", "tx1", "tx2", "tx3", "0", "1", "2", "3"]
ALLOWED_RX_MODES = ["combine_4rx", "rx0", "rx1", "rx2", "rx3"]

def validate_params(params):
    """
    Validate the input configuration parameter dictionary.
    Raises ValueError if validation fails.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters must be passed as a dictionary class.")
        
    required_keys = ["serial", "qcn_file", "rat", "tx", "network_mask"]
    for key in required_keys:
        if key not in params:
            raise ValueError(f"Missing required parameter key: '{key}'")
            
    # 1. Validate serial
    serial = params["serial"]
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("Parameter 'serial' (ADB serial number) must be a non-empty string.")
        
    # 2. Validate QCN File Path (must be absolute or full path and must exist)
    qcn_file = params["qcn_file"]
    if not os.path.isabs(qcn_file):
        # Resolve to absolute path to guarantee full path
        qcn_file = os.path.abspath(qcn_file)
        params["qcn_file"] = qcn_file
        
    if not os.path.exists(qcn_file):
        raise ValueError(f"QCN file path '{qcn_file}' does not exist. Please specify a valid full path.")
        
    # 3. Validate RAT
    rat = params["rat"].upper() if isinstance(params["rat"], str) else ""
    if rat not in ALLOWED_RATS:
        raise ValueError(f"Invalid RAT: '{params['rat']}'. Must be one of: {ALLOWED_RATS}")
        
    # 4. Validate TX parameter
    tx_raw = str(params["tx"]).lower()
    if tx_raw not in ALLOWED_TX_VALUES:
        raise ValueError(f"Invalid 'tx': '{params['tx']}'. Must be one of: {ALLOWED_TX_VALUES}")
    tx_normalized = tx_raw if tx_raw.startswith("tx") else f"tx{tx_raw}"
    params["tx"] = tx_normalized
        
    # 6. Validate RX mode
    if rat in ["LTE", "LTE_ONLY"]:
        if "rx_mode" not in params:
            raise ValueError("Parameter 'rx_mode' is required when RAT is LTE.")
        rx_mode = params["rx_mode"].lower() if isinstance(params["rx_mode"], str) else ""
        if rx_mode not in ALLOWED_RX_MODES:
            raise ValueError(f"Invalid 'rx_mode': '{params['rx_mode']}'. Must be one of: {ALLOWED_RX_MODES}")
            
    # 7. Validate SIM Slot
    sim_slot = params.get("sim_slot", 0)
    if sim_slot not in (0, 1):
        raise ValueError(f"Invalid 'sim_slot': {sim_slot}. Must be 0 or 1.")
        
    # 8. Validate Network Mask
    mask_str = params["network_mask"].upper() if isinstance(params["network_mask"], str) else ""
    try:
        android_network_manager.NetworkMask[mask_str]
    except KeyError:
        raise ValueError(f"Invalid 'network_mask': '{params['network_mask']}'. Must be one of: "
                         f"{[m.name for m in android_network_manager.NetworkMask]}")
        
    print("[+] Parameters validated successfully for Qualcomm flow.")
    return True

def get_adb_usb_config(serial: str = "") -> str:
    """
    Get 'sys.usb.config' property via ADB.
    """
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["shell", "getprop", "sys.usb.config"])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            return res.stdout.strip()
        else:
            if res.stderr:
                print(f"[WARNING] 获取 sys.usb.config 失败: {res.stderr.strip()}")
            return ""
    except Exception as e:
        print(f"[ERROR] 执行 ADB 获取 sys.usb.config 异常: {e}")
        return ""

def get_fastboot_devices() -> list:
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

def wait_for_fastboot_device(target_serial: str = "", timeout: int = 20) -> tuple:
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

def run_qc_flow(params):
    """
    Run the full end-to-end Qualcomm testing orchestration flow:
    0. Verify USB configuration (sys.usb.config). If not diag, switch to bootmode qcom and reboot.
    1. Write and Query NV73841 & NV73971.
    2. Change Network Type.
    3. Configure LTE RX Path (skipped in NR mode).
    4. Restore XQCN backup (moved to last step).
    """
    try:
        # Validate parameters dictionary
        validate_params(params)
    except ValueError as e:
        print(f"\n[PARAM ERROR] Parameter validation failed: {e}")
        sys.exit(1)

    serial = params["serial"]
    qcn_file = params["qcn_file"]
    rat = params["rat"].upper()
    tx_val = str(params["tx"]).lower()
    sim_slot = params.get("sim_slot", 0)
    network_mask = params["network_mask"].upper()
    
    print("\n" + "="*70)
    print("STARTING QUALCOMM ANTENNA TESTING ORCHESTRATION FLOW")
    print("="*70)

    # 检查 sys.usb.config 是否包含 diag 端口
    print("\n--- 检查 USB 配置 (sys.usb.config) ---")
    usb_config = get_adb_usb_config(serial)
    print(f"[*] 当前设备 sys.usb.config: '{usb_config}'")

    if "diag" not in usb_config.lower():
        if params.get("_diag_reboot_attempted", False):
            print(f"\n[ERROR] 设备已尝试切换 bootmode qcom 并重启，但 sys.usb.config 仍不包含 'diag' (当前值: '{usb_config}')。")
            return False

        print("[*] sys.usb.config 不包含 'diag'，即将重启进入 bootloader 切换至 qcom 模式...")
        params["_diag_reboot_attempted"] = True

        # 1. adb reboot bootloader
        adb_reboot_cmd = ["adb"]
        if serial:
            adb_reboot_cmd.extend(["-s", serial])
        adb_reboot_cmd.extend(["reboot", "bootloader"])
        print(f"[*] 执行命令: {' '.join(adb_reboot_cmd)}")
        subprocess.run(adb_reboot_cmd, check=False)

        # 2. 执行 fastboot devices 检查，若未识别到设备提醒安装驱动
        print("[*] 等待设备进入 bootloader 模式并执行 fastboot devices 检查...")
        fb_ok, fb_serial = wait_for_fastboot_device(serial, timeout=20)
        if not fb_ok:
            print("\n" + "!"*70)
            print("[ERROR] fastboot devices 未识别到设备，请先安装驱动！")
            print("!"*70 + "\n")
            return False

        print(f"[+] fastboot 成功识别到设备: {fb_serial}")

        # 3. fastboot oem config bootmode qcom
        target_fb = fb_serial if fb_serial else serial
        fb_config_cmd = ["fastboot"]
        if target_fb:
            fb_config_cmd.extend(["-s", target_fb])
        fb_config_cmd.extend(["oem", "config", "bootmode", "qcom"])
        print(f"[*] 执行命令: {' '.join(fb_config_cmd)}")
        res_cfg = subprocess.run(fb_config_cmd, capture_output=True, text=True, check=False)
        out_cfg = ((res_cfg.stdout or "") + "\n" + (res_cfg.stderr or "")).strip()
        if out_cfg:
            print(f"  {out_cfg}")

        # 4. fastboot reboot
        fb_reboot_cmd = ["fastboot"]
        if target_fb:
            fb_reboot_cmd.extend(["-s", target_fb])
        fb_reboot_cmd.extend(["reboot"])
        print(f"[*] 执行命令: {' '.join(fb_reboot_cmd)}")
        res_rb = subprocess.run(fb_reboot_cmd, capture_output=True, text=True, check=False)
        out_rb = ((res_rb.stdout or "") + "\n" + (res_rb.stderr or "")).strip()
        if out_rb:
            print(f"  {out_rb}")

        # 5. 等待开机并重新连接 ADB
        print("[*] 等待设备重启并重新连接 ADB...")
        if not wait_for_adb_device(serial, timeout=120):
            print("[ERROR] 等待设备重启超时，ADB 未重新连接！")
            return False

        # 6. 再次调用 run_qc_flow 函数
        print("\n[*] 正在重新调用 run_qc_flow 函数...")
        return run_qc_flow(params)

    print("[+] sys.usb.config 已包含 'diag'，继续执行测试流程。")
    
    # Step 1: Write and Query NV73841 & NV73971
    print("\n--- Step 1: Writing and Querying NV Items ---")

    # 1a. Modify NV 73971 (ASDiv bands master) to JSON constant
    print("[*] Setting NV 73971 (ASDiv bands master) to JSON constant...")
    qc_nv.modify_nv_for_device(target_adb_serial=serial, nv_id="73971", nv_value=qc_nv.NV_73971_JSON)
    qc_nv.query_nv_for_device(target_adb_serial=serial, nv_id="73971")

    # 1b. Modify NV 73841 according to selected tx
    print(f"[*] Setting NV 73841 according to TX target '{tx_val.upper()}'...")
    qc_nv.set_antenna_tx(target_adb_serial=serial, tx=tx_val)
    
    # Step 2: Switch Network Type via android_network_manager
    print("\n--- Step 2: Setting Network Type Mask ---")
    mask_enum = android_network_manager.NetworkMask[network_mask]
        
    net_switch_ok = android_network_manager.set_allowed_network_type(
        sim_slot=sim_slot,
        mask=mask_enum,
        device_id=serial
    )
    if not net_switch_ok:
        print("[WARNING] Network switch failed. Proceeding with remaining steps.")
        
    # Step 3: Switch LTE RX Path via qc_lte_rx
    print("\n--- Step 3: Configuring LTE RX Paths ---")
    if rat in ["NR", "NR_ONLY"]:
        print("[INFO] Target network mode is NR (5G). SKIPPING Step 3 (LTE RX selection).")
    else:
        rx_mode = params["rx_mode"].lower()
        print(f"[*] Setting LTE Rx selection to mode: '{rx_mode}'")
        rx_ok = qc_lte_rx.switch_lte_rx(mode=rx_mode, client_name="QcOrchestrationLteRx")
        if not rx_ok:
            print("[WARNING] LTE Rx path selection returned False.")
            
    # Step 4: Restore XQCN (moved to last step)
    print("\n--- Step 4: Restoring QCN/XQCN Backup ---")
    print(f"[*] Restoring backup from full path: {qcn_file}")
    qc_restore_xqcn.restore_xqcn_for_device(target_adb_serial=serial, xqcn_path=qcn_file)
    # Pause briefly to allow QUTS services to settle down after restore
    time.sleep(2)
    
    print("\n" + "="*70)
    print("QUALCOMM ANTENNA TESTING ORCHESTRATION FLOW COMPLETE")
    print("="*70 + "\n")
    return True

def main():
    parser = argparse.ArgumentParser(description="Qualcomm End-to-End Antenna Orchestration Script")
    parser.add_argument("--serial", required=True, help="Target device ADB serial number")
    parser.add_argument("--qcn-file", required=True, help="Absolute full path to the backup .qcn / .xqcn file")
    parser.add_argument("--rat", required=True, choices=["LTE", "LTE_ONLY", "NR", "NR_ONLY"], 
                        help="Target network tech: LTE or NR", type=str.upper)
    parser.add_argument("--tx", required=True, choices=["tx0", "tx1", "tx2", "tx3", "0", "1", "2", "3"], 
                        help="TX antenna target: tx0/0 (NV=0), tx1/1 (NV=17), tx2/2 (NV=34), tx3/3 (NV=51)", type=str.lower)
    parser.add_argument("--rx-mode", choices=["combine_4rx", "rx0", "rx1", "rx2", "rx3"], 
                        help="LTE RX path override mode. Required if RAT is LTE.", type=str.lower)
    parser.add_argument("--sim-slot", type=int, choices=[0, 1], default=0, 
                        help="SIM card slot: 0 for SIM1 (default), 1 for SIM2")
    parser.add_argument("--network-mask", required=True, choices=["LTE_ONLY", "NR_ONLY", "NR_LTE", "DEFAULT"], 
                        help="Network type mask from android_network_manager", type=str.upper)
                        
    args = parser.parse_args()
    
    # Package parameters into dictionary
    params = {
        "serial": args.serial,
        "qcn_file": args.qcn_file,
        "rat": args.rat,
        "tx": args.tx,
        "sim_slot": args.sim_slot,
        "network_mask": args.network_mask
    }
    if args.rx_mode is not None:
        params["rx_mode"] = args.rx_mode
        
    try:
        # Execute the main orchestrated flow
        success = run_qc_flow(params)
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] Flow execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
