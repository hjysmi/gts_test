#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
MediaTek End-to-End Antenna Testing Orchestration Script (mtk_main.py)
Orchestrates device validation, MTK logger management and network mask via AdbDevice,
and high-speed RF TX/RX testing via MtkModemSession.
"""

import sys
import os
import argparse

from adb_device import AdbDevice, FlowResult, check_adb_device, NetworkMask
from mtk_modem import MtkModemSession, RX_MODES_MAP, ALLOWED_RX_MODES

# Defined ranges and sets for validation
LTE_FDD_BANDS = {1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 17, 18, 19, 20, 21, 25, 26, 28, 30, 31, 32, 66, 71}
LTE_TDD_BANDS = {34, 37, 38, 39, 40, 41, 42, 43, 46, 48}

ALLOWED_RATS = ["LTE", "LTE_FDD", "LTE_TDD", "NR_SA", "NR_ONLY", "NR", "NR_NSA", "NR_LTE"]

# Mapping from RAT selection to canonical RAT type and Android network mask
RAT_CONFIG_MAP = {
    # 4G FDD
    "LTE": {"rat": "LTE", "mask": "LTE_ONLY"},
    "LTE_FDD": {"rat": "LTE", "mask": "LTE_ONLY"},
    # 4G TDD
    "LTE_TDD": {"rat": "LTE_TDD", "mask": "LTE_ONLY"},
    # 5G 独立组网 (SA)
    "NR_SA": {"rat": "NR", "mask": "NR_ONLY"},
    "NR_ONLY": {"rat": "NR", "mask": "NR_ONLY"},
    # 5G 非独立组网 (NSA) - 必须保留 LTE 锚点避免掉网
    "NR_NSA": {"rat": "NR", "mask": "NR_LTE"},
    "NR_LTE": {"rat": "NR", "mask": "NR_LTE"},
    "NR": {"rat": "NR", "mask": "NR_LTE"},
}


def validate_params(params):
    """
    Validate the configuration parameter dictionary.
    Raises ValueError if validation fails.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters must be passed as a dictionary class.")
        
    # Allow rx_scenario as backward-compatible fallback for rx_mode
    if "rx_mode" not in params and "rx_scenario" in params:
        params["rx_mode"] = params["rx_scenario"]

    required_keys = ["serial", "rat", "band", "tx_state", "ttps_port", "sim_slot", "rx_mode"]
    for key in required_keys:
        if key not in params:
            raise ValueError(f"Missing required parameter key: '{key}'")
            
    # Validate serial and check presence in adb devices
    serial = params["serial"]
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("Parameter 'serial' (ADB serial number) must be a non-empty string.")
    serial = serial.strip()
    params["serial"] = serial

    adb_ok, adb_err = check_adb_device(serial)
    if not adb_ok:
        raise ValueError(f"ADB 设备检测失败: {adb_err}")

    # Validate RAT and derive network_mask
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
        if canonical_rat in ["LTE", "LTE_TDD"] and user_mask != "LTE_ONLY":
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (LTE) is incompatible with "
                             f"network_mask '{user_mask}'. Expected 'LTE_ONLY'.")
        elif rat_raw in ["NR_SA", "NR_ONLY"] and user_mask != "NR_ONLY":
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (5G SA) is incompatible with "
                             f"network_mask '{user_mask}'. Expected 'NR_ONLY'.")
        elif rat_raw in ["NR_NSA", "NR_LTE"] and user_mask not in ["NR_LTE", "DEFAULT"]:
            raise ValueError(f"Parameter conflict: RAT '{rat_raw}' (5G NSA) is incompatible with "
                             f"network_mask '{user_mask}'. NSA requires 'NR_LTE' or 'DEFAULT'.")
        params["network_mask"] = user_mask
    else:
        params["network_mask"] = derived_mask

    # Validate Band and its alignment with RAT
    band = params["band"]
    if not isinstance(band, int) or band <= 0:
        raise ValueError(f"Invalid band: '{band}'. Must be a positive integer.")
        
    if canonical_rat == "LTE":
        # Must be LTE FDD
        if band not in LTE_FDD_BANDS:
            if band in LTE_TDD_BANDS:
                raise ValueError(f"Invalid configuration: Band {band} is an LTE TDD band, but RAT is set to LTE (FDD).")
            else:
                raise ValueError(f"Invalid configuration: Band {band} is not a recognized LTE FDD band. LTE FDD bands: {sorted(list(LTE_FDD_BANDS))}")
                
        # For LTE FDD, Rx TAS State must NOT be set
        if params.get("rx_state") is not None:
            raise ValueError(f"Invalid configuration: 'rx_state' (Rx TAS State) was set to {params['rx_state']}, but Rx TAS State must not be set for LTE FDD.")
            
    elif canonical_rat == "LTE_TDD":
        # Must be LTE TDD
        if band not in LTE_TDD_BANDS:
            if band in LTE_FDD_BANDS:
                raise ValueError(f"Invalid configuration: Band {band} is an LTE FDD band, but RAT is set to LTE_TDD.")
            else:
                raise ValueError(f"Invalid configuration: Band {band} is not a recognized LTE TDD band. LTE TDD bands: {sorted(list(LTE_TDD_BANDS))}")
                
        # For LTE TDD, Rx TAS State is required
        if params.get("rx_state") is None:
            raise ValueError("Invalid configuration: 'rx_state' (Rx TAS State) is required when RAT is LTE_TDD.")
            
    elif canonical_rat == "NR":
        # For NR, Rx TAS State is required
        if params.get("rx_state") is None:
            raise ValueError("Invalid configuration: 'rx_state' (Rx TAS State) is required when RAT is NR.")
            
    # Validate TAS States
    tx_state = params["tx_state"]
    if tx_state not in range(24) and tx_state != 255:
        raise ValueError(f"Invalid 'tx_state': {tx_state}. Must be between 0 and 23, or 255.")
        
    rx_state = params.get("rx_state")
    if rx_state is not None:
        if rx_state not in range(24) and rx_state != 255:
            raise ValueError(f"Invalid 'rx_state': {rx_state}. Must be between 0 and 23, or 255.")
            
    # Validate TTPS Port
    ttps_port = params["ttps_port"]
    if ttps_port not in (0, 1):
        raise ValueError(f"Invalid 'ttps_port': {ttps_port}. Must be 0 or 1.")
        
    # Validate SIM Slot
    sim_slot = params["sim_slot"]
    if sim_slot not in (0, 1):
        raise ValueError(f"Invalid 'sim_slot': {sim_slot}. Must be 0 (SIM 1) or 1 (SIM 2).")
                         
    # Validate RX Mode
    rx_mode_raw = str(params["rx_mode"]).lower() if "rx_mode" in params and params["rx_mode"] is not None else ""
    if rx_mode_raw not in RX_MODES_MAP:
        raise ValueError(f"Invalid 'rx_mode': '{params.get('rx_mode')}'. Must be one of: {ALLOWED_RX_MODES}")
    params["rx_mode"] = rx_mode_raw

    print("[+] Parameters validated successfully.")
    return True


def run_mtk_flow(params):
    """
    Run the full end-to-end testing orchestration flow:
    1. Stop MTK logger via AdbDevice.
    2. Switch MTK logger to USB mode via AdbDevice.
    3. Start MTK logger via AdbDevice.
    4. Connect to MtkModemSession once.
    5. Set allowed network type via AdbDevice.
    6. Perform TX antenna switching via MtkModemSession.
    7. Perform RX antenna diversity testing via MtkModemSession.
    8. Save modem diagnostic logs to disk (.elg) via MtkModemSession.
    9. Stop MTK logger via AdbDevice.
    """
    print("\n" + "="*70)
    print("STARTING MTK ANTENNA TESTING ORCHESTRATION FLOW")
    print("="*70)
    try:
        validate_params(params)
    except ValueError as e:
        err_msg = f"Parameter validation failed: {e}"
        print(f"\n[PARAM ERROR] {err_msg}")
        return FlowResult(False, err_msg)

    serial = params["serial"]
    adb_dev = AdbDevice(serial)

    # Step 1: Stop log
    print("\n--- Step 1: Stopping MTK Logger ---")
    adb_dev.control_mtk_logger("stop")
    
    # Step 2: Switch modem mode to USB mode
    print("\n--- Step 2: Setting Modem Logging Mode to USB ---")
    adb_dev.control_mtk_logger("switch_usb")
    
    # Step 3: Start log
    print("\n--- Step 3: Starting MTK Logger ---")
    adb_dev.control_mtk_logger("start")
    
    try:
        with MtkModemSession(target_serial=serial, database="auto") as modem:
            # Step 4: Switch network type via AdbDevice
            print("\n--- Step 4: Switching Network Type ---")
            res_net = adb_dev.set_network_mask(mask=params["network_mask"], sim_slot=params["sim_slot"])
            if not res_net:
                err_msg = f"Step 4: 设置网络制式掩码 '{params['network_mask']}' 失败: {res_net.error_message}"
                print(f"[ERROR] {err_msg}")
                return FlowResult(False, err_msg)
            
            # Step 5: Switch TX via MtkModemSession
            print("\n--- Step 5: Setting TX Antenna Force ---")
            res_tx = modem.set_tx_antenna(
                rat=params["rat"],
                band=params["band"],
                tx_state=params["tx_state"],
                rx_state=params.get("rx_state"),
                ttps_port=params["ttps_port"]
            )
            if not res_tx:
                err_msg = f"Step 5: 设置 TX 强迫发射天线失败: {res_tx.error_message}"
                print(f"[ERROR] {err_msg}")
                return FlowResult(False, err_msg)
                
            # Step 6: Switch RX via MtkModemSession
            print("\n--- Step 6: Setting RX Antenna Test ---")
            res_rx = modem.set_rx_mode(
                rx_mode=params["rx_mode"],
                rat=params["rat"]
            )
            if not res_rx:
                err_msg = f"Step 6: 设置 RX 接收分集测试失败: {res_rx.error_message}"
                print(f"[ERROR] {err_msg}")
                return FlowResult(False, err_msg)

            # Step 7: Save modem logs
            print("\n--- Step 7: Saving MTK Modem Diagnostic Logs ---")
            out_dir = params.get("out_dir", ".")
            log_file = params.get("log_file", "antenna_test_log.elg")
            res_log = modem.save_logs(out_dir=out_dir, log_file=log_file)
            if not res_log:
                err_msg = f"Step 7: 保存调制解调器诊断日志失败: {res_log.error_message}"
                print(f"[ERROR] {err_msg}")
                return FlowResult(False, err_msg)

    except Exception as e:
        err_msg = f"MACE 调制解调器会话异常: {e}"
        print(f"[ERROR] {err_msg}")
        return FlowResult(False, err_msg)
    finally:
        # Step 8: Stop log
        print("\n--- Step 8: Stopping MTK Logger ---")
        adb_dev.control_mtk_logger("stop")
    
    print("\n" + "="*70)
    print("[SUCCESS] All steps in orchestration flow completed successfully!")
    print("="*70 + "\n")
    return FlowResult(True, "")


# Backward-compatible alias for module integration
run_orchestration_flow = run_mtk_flow


def main():
    parser = argparse.ArgumentParser(description="MTK End-to-End Antenna Orchestration Script")
    parser.add_argument("--serial", required=True, help="Target device ADB serial number")
    parser.add_argument("--rat", required=True, 
                        choices=["LTE", "LTE_TDD", "NR_SA", "NR_NSA", "NR", "NR_ONLY", "NR_LTE"], 
                        help="RAT & network mode: LTE (FDD), LTE_TDD, NR_SA/NR_ONLY (5G SA), NR_NSA/NR_LTE/NR (5G NSA)", 
                        type=str.upper)
    parser.add_argument("--band", required=True, type=int, help="Band number")
    parser.add_argument("--tx-state", required=True, type=int, help="Tx TAS State (0-23, or 255)")
    parser.add_argument("--rx-state", type=int, help="Rx TAS State (0-23, or 255). Required for LTE_TDD and NR.")
    parser.add_argument("--ttps-port", required=True, type=int, help="TTPS TX port (0 or 1)")
    parser.add_argument("--sim-slot", required=True, type=int, choices=[0, 1], help="SIM Slot: 0 for SIM1, 1 for SIM2")
    parser.add_argument("--rx-mode", required=True, 
                        choices=["combine_4rx", "combine_2rx", "rx0", "rx1", "rx2", "rx3"], 
                        help="RX Mode: combine_4rx, combine_2rx, rx0, rx1, rx2, or rx3", 
                        type=str.lower)
    parser.add_argument("--out-dir", default=".", help="Directory to save capture logs (default: .)")
    parser.add_argument("--log-file", default="antenna_test_log.elg", help="Log filename (default: antenna_test_log.elg)")
                        
    args = parser.parse_args()
    
    params = {
        "serial": args.serial,
        "rat": args.rat,
        "band": args.band,
        "tx_state": args.tx_state,
        "ttps_port": args.ttps_port,
        "sim_slot": args.sim_slot,
        "rx_mode": args.rx_mode,
        "out_dir": args.out_dir,
        "log_file": args.log_file
    }
    if args.rx_state is not None:
        params["rx_state"] = args.rx_state
        
    try:
        res = run_mtk_flow(params)
        if not res:
            err = res.error_message if isinstance(res, FlowResult) and res.error_message else "MTK 流程执行失败。"
            print(f"\n[FATAL ERROR] {err}")
            sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] Flow execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
