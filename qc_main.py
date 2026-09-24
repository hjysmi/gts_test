#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qualcomm End-to-End Antenna Testing Orchestration Script (qc_main.py)
Orchestrates device validation, diagnostic port configuration via AdbDevice,
and high-speed RF testing / XQCN recovery via QualcommModemSession.
"""

import warnings
# Ignore QUTS internal SyntaxWarnings caused by backslashes in docstrings
warnings.filterwarnings("ignore", category=SyntaxWarning)

import os
import sys
import argparse
import time

from adb_device import AdbDevice, FlowResult, check_adb_device, NetworkMask
from qc_modem import QualcommModemSession

# Allowed values for validation
ALLOWED_RATS = ["LTE", "LTE_ONLY", "NR_SA", "NR_ONLY", "NR", "NR_NSA", "NR_LTE"]
ALLOWED_TX_VALUES = ["tx0", "tx1", "tx2", "tx3", "0", "1", "2", "3"]
ALLOWED_RX_MODES = ["combine_4rx", "rx0", "rx1", "rx2", "rx3"]

# Mapping from RAT selection to canonical RAT type and Android network mask
RAT_CONFIG_MAP = {
    "LTE": {"rat": "LTE", "mask": "LTE_ONLY"},
    "LTE_ONLY": {"rat": "LTE", "mask": "LTE_ONLY"},
    "NR_SA": {"rat": "NR_SA", "mask": "NR_ONLY"},
    "NR_ONLY": {"rat": "NR_SA", "mask": "NR_ONLY"},
    "NR": {"rat": "NR_SA", "mask": "NR_ONLY"},
    "NR_NSA": {"rat": "NR_NSA", "mask": "NR_LTE"},
    "NR_LTE": {"rat": "NR_NSA", "mask": "NR_LTE"},
}


def validate_params(params):
    """
    Validate the input configuration parameter dictionary.
    Raises ValueError if validation fails.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters must be passed as a dictionary class.")
        
    required_keys = ["serial", "qcn_file", "rat", "tx"]
    for key in required_keys:
        if key not in params:
            raise ValueError(f"Missing required parameter key: '{key}'")
            
    # 1. Validate serial and check presence in adb devices
    serial = params["serial"]
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("Parameter 'serial' (ADB serial number) must be a non-empty string.")
    serial = serial.strip()
    params["serial"] = serial
    
    adb_ok, adb_err = check_adb_device(serial)
    if not adb_ok:
        raise ValueError(f"ADB 设备检测失败: {adb_err}")
        
    # 2. Validate QCN File Path (must be absolute or full path and must exist)
    qcn_file = params["qcn_file"]
    if not os.path.isabs(qcn_file):
        qcn_file = os.path.abspath(qcn_file)
        params["qcn_file"] = qcn_file
        
    if not os.path.exists(qcn_file):
        raise ValueError(f"QCN file path '{qcn_file}' does not exist. Please specify a valid full path.")
        
    # 3. Validate RAT and derive network_mask
    rat_raw = params["rat"].upper() if isinstance(params["rat"], str) else ""
    if rat_raw not in ALLOWED_RATS:
        raise ValueError(f"Invalid RAT: '{params['rat']}'. Must be one of: {ALLOWED_RATS}")
        
    config = RAT_CONFIG_MAP[rat_raw]
    canonical_rat = config["rat"]
    derived_mask = config["mask"]
    params["rat"] = canonical_rat

    # Parameter conflict validation for network_mask (if explicitly passed in dict)
    if "network_mask" in params and params["network_mask"]:
        user_mask = params["network_mask"].upper()
        try:
            NetworkMask[user_mask]
        except KeyError:
            raise ValueError(f"Invalid 'network_mask': '{user_mask}'. Must be one of: "
                             f"{[m.name for m in NetworkMask]}")
        # Conflict checks
        if canonical_rat == "LTE" and user_mask != "LTE_ONLY":
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (LTE) is incompatible with "
                             f"network_mask '{user_mask}'. Expected 'LTE_ONLY'.")
        elif canonical_rat == "NR_SA" and user_mask != "NR_ONLY":
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (5G SA) is incompatible with "
                             f"network_mask '{user_mask}'. Expected 'NR_ONLY'.")
        elif canonical_rat == "NR_NSA" and user_mask not in ["NR_LTE", "DEFAULT"]:
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (5G NSA) is incompatible with "
                             f"network_mask '{user_mask}'. NSA requires 'NR_LTE' or 'DEFAULT'.")
        params["network_mask"] = user_mask
    else:
        params["network_mask"] = derived_mask
        
    # 4. Validate TX parameter
    tx_raw = str(params["tx"]).lower()
    if tx_raw not in ALLOWED_TX_VALUES:
        raise ValueError(f"Invalid 'tx': '{params['tx']}'. Must be one of: {ALLOWED_TX_VALUES}")
    tx_normalized = tx_raw if tx_raw.startswith("tx") else f"tx{tx_raw}"
    params["tx"] = tx_normalized
        
    # 5. Validate RX mode
    if canonical_rat == "LTE":
        if "rx_mode" not in params or not params["rx_mode"]:
            raise ValueError("Parameter 'rx_mode' is required when RAT is LTE.")
        rx_mode = params["rx_mode"].lower() if isinstance(params["rx_mode"], str) else ""
        if rx_mode not in ALLOWED_RX_MODES:
            raise ValueError(f"Invalid 'rx_mode': '{params['rx_mode']}'. Must be one of: {ALLOWED_RX_MODES}")
    else:
        if "rx_mode" in params and params["rx_mode"]:
            print(f"[INFO] Target network mode is 5G ({canonical_rat}). 'rx_mode'='{params['rx_mode']}' is not applicable and will be safely ignored.")
            
    # 6. Validate SIM Slot
    sim_slot = params.get("sim_slot", 0)
    if sim_slot not in (0, 1):
        raise ValueError(f"Invalid 'sim_slot': {sim_slot}. Must be 0 or 1.")
        
    print("[+] Parameters validated successfully for Qualcomm flow.")
    return True


def run_qc_flow(params):
    """
    Run the full end-to-end Qualcomm testing orchestration flow:
    0. Verify USB configuration (sys.usb.config). If not diag, switch to bootmode qcom.
    1. Write and Query NV73841 & NV73971 via persistent QualcommModemSession.
    2. Change Network Type via AdbDevice.
    3. Configure LTE RX Path (skipped in NR mode).
    4. Restore XQCN backup.
    """
    try:
        validate_params(params)
    except ValueError as e:
        err_msg = f"Parameter validation failed: {e}"
        print(f"\n[PARAM ERROR] {err_msg}")
        return FlowResult(False, err_msg)

    serial = params["serial"]
    qcn_file = params["qcn_file"]
    rat = params["rat"].upper()
    tx_val = str(params["tx"]).lower()
    sim_slot = params.get("sim_slot", 0)
    network_mask = params["network_mask"].upper()
    
    adb_dev = AdbDevice(serial)

    print("\n" + "="*70)
    print("STARTING QUALCOMM ANTENNA TESTING ORCHESTRATION FLOW")
    print("="*70)

    # 0. 检查并确保 DIAG 端口处于开启状态 (若非 diag 则自动切换 bootmode qcom 并等待系统就绪)
    print("\n--- Step 0: 检查并配置 QCOM DIAG 端口模式 ---")
    res_diag = adb_dev.ensure_diag_mode()
    if not res_diag:
        return FlowResult(False, f"配置 QCOM DIAG 端口失败: {res_diag.error_message}")

    try:
        with QualcommModemSession(target_serial=serial) as modem:
            # Step 1: Write and Query NV73841 & NV73971
            print("\n--- Step 1: Writing and Querying NV Items ---")
            res_tx = modem.set_antenna_tx(tx_val)
            if not res_tx:
                return FlowResult(False, f"Step 1: 写入 TX NV 失败: {res_tx.error_message}")

            # Step 2: Switch Network Type via AdbDevice
            print("\n--- Step 2: Setting Network Type Mask ---")
            res_net = adb_dev.set_network_mask(mask=network_mask, sim_slot=sim_slot)
            if not res_net:
                return FlowResult(False, f"Step 2: 切换网络掩码 '{network_mask}' 失败: {res_net.error_message}")

            # Step 3: Switch LTE RX Path via QualcommModemSession
            print("\n--- Step 3: Configuring LTE RX Paths ---")
            if rat in ["NR", "NR_ONLY", "NR_SA", "NR_NSA", "NR_LTE"]:
                print(f"[INFO] Target network mode is 5G ({rat}). SKIPPING Step 3 (LTE RX selection).")
            else:
                rx_mode = params["rx_mode"].lower()
                res_rx = modem.switch_lte_rx(mode=rx_mode)
                if not res_rx:
                    return FlowResult(False, f"Step 3: 设置 LTE Rx 分集模式 '{rx_mode}' 失败: {res_rx.error_message}")

            # Step 4: Restore XQCN via QualcommModemSession
            print("\n--- Step 4: Restoring QCN/XQCN Backup ---")
            res_restore = modem.restore_xqcn(qcn_file)
            if not res_restore:
                return FlowResult(False, f"Step 4: 还原 QCN/XQCN 备份文件失败: {res_restore.error_message}")

            # Pause briefly to allow QUTS services to settle down after restore
            time.sleep(2)

    except Exception as e:
        err_msg = f"QUTS 调制解调器会话异常: {e}"
        print(f"[ERROR] {err_msg}")
        return FlowResult(False, err_msg)

    print("\n" + "="*70)
    print("QUALCOMM ANTENNA TESTING ORCHESTRATION FLOW COMPLETE")
    print("="*70 + "\n")
    return FlowResult(True, "")


def main():
    parser = argparse.ArgumentParser(description="Qualcomm End-to-End Antenna Orchestration Script")
    parser.add_argument("--serial", required=True, help="Target device ADB serial number")
    parser.add_argument("--qcn-file", required=True, help="Absolute full path to the backup .qcn / .xqcn file")
    parser.add_argument("--rat", required=True, 
                        choices=["LTE", "LTE_ONLY", "NR_SA", "NR_ONLY", "NR", "NR_NSA", "NR_LTE"], 
                        help="Target RAT & network mode: LTE/LTE_ONLY (4G), NR_SA/NR_ONLY/NR (5G SA), NR_NSA/NR_LTE (5G NSA)", 
                        type=str.upper)
    parser.add_argument("--tx", required=True, choices=["tx0", "tx1", "tx2", "tx3", "0", "1", "2", "3"], 
                        help="TX antenna target: tx0/0 (NV=0), tx1/1 (NV=17), tx2/2 (NV=34), tx3/3 (NV=51)", type=str.lower)
    parser.add_argument("--rx-mode", choices=["combine_4rx", "rx0", "rx1", "rx2", "rx3"], 
                        help="LTE RX path override mode. Required if RAT is LTE.", type=str.lower)
    parser.add_argument("--sim-slot", type=int, choices=[0, 1], default=0, 
                        help="SIM card slot: 0 for SIM1 (default), 1 for SIM2")
                        
    args = parser.parse_args()
    
    # Package parameters into dictionary
    params = {
        "serial": args.serial,
        "qcn_file": args.qcn_file,
        "rat": args.rat,
        "tx": args.tx,
        "sim_slot": args.sim_slot,
    }
    if args.rx_mode is not None:
        params["rx_mode"] = args.rx_mode
        
    try:
        res = run_qc_flow(params)
        if not res:
            err = res.error_message if isinstance(res, FlowResult) and res.error_message else "Qualcomm 流程执行失败。"
            print(f"\n[FATAL ERROR] {err}")
            sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] Flow execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
