import sys
import os
import argparse
import subprocess
import mtk_atc_md
import mtk_rx
import mtk_tx
import android_network_manager

# Defined ranges and sets for validation
LTE_FDD_BANDS = {1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 17, 18, 19, 20, 21, 25, 26, 28, 30, 31, 32, 66, 71}
LTE_TDD_BANDS = {34, 37, 38, 39, 40, 41, 42, 43, 46, 48}

# Mapping RX mode names to their original integer scenario IDs
RX_MODES_MAP = {
    "combine_4rx": 1,
    "combine_2rx": 6,
    "rx0": 2,
    "rx1": 3,
    "rx2": 4,
    "rx3": 5
}
ALLOWED_RX_MODES = list(RX_MODES_MAP.keys())

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

class FlowResult(tuple):
    """
    Result representing (success: bool, error_message: str).
    Evaluates to True if success is True, False otherwise.
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

def check_adb_device(target_serial: str) -> tuple:
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
            android_network_manager.NetworkMask[user_mask]
        except KeyError:
            raise ValueError(f"Invalid 'network_mask': '{user_mask}'. Must be one of: "
                             f"{[m.name for m in android_network_manager.NetworkMask]}")
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
    1. Stop MTK logger.
    2. Switch MTK logger to USB mode.
    3. Start MTK logger.
    4. Connect to MACE ONCE (Device is now connected before switching network/switching TX/RX).
    5. Call android_network_manager to switch network type.
    6. Perform TX switching via mtk_tx.py reusing the device.
    7. Perform RX switching via mtk_rx.py reusing the device.
    8. Stop MTK logger.
    """
    print("\n" + "="*70)
    print("STARTING MTK ANTENNA TESTING ORCHESTRATION FLOW")
    print("="*70)
    try:
        # Validate parameters dictionary
        validate_params(params)
    except ValueError as e:
        err_msg = f"Parameter validation failed: {e}"
        print(f"\n[PARAM ERROR] {err_msg}")
        return FlowResult(False, err_msg)

    serial = params["serial"]

    # Step 1: Stop log
    print("\n--- Step 1: Stopping MTK Logger ---")
    mtk_rx.control_mtk_logger("stop", device_id=serial)
    
    # Step 2: Switch modem mode to USB mode
    print("\n--- Step 2: Setting Modem Logging Mode to USB ---")
    mtk_rx.control_mtk_logger("switch_usb", device_id=serial)
    
    # Step 3: Start log
    print("\n--- Step 3: Starting MTK Logger ---")
    mtk_rx.control_mtk_logger("start", device_id=serial)
    
    device = None
    tx_ok = False
    rx_ok = False
    
    try:
        # Connect to MACE ONCE (before Step 4 Network Type Switch)
        print("\n--- Establishing Connection ---")
        print(f"[*] Connecting to MACE device ONCE (device_id={serial}) for shared use in network/TX/RX switching...")
        try:
            device = mtk_atc_md.connect_to_device(device_id=serial, database="auto")
        except Exception as e:
            err_msg = f"连接 MACE 调制解调器设备失败: {e}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
        
        # Step 4: Switch network type via android_network_manager
        print("\n--- Step 4: Switching Network Type ---")
        mask_enum = android_network_manager.NetworkMask[params["network_mask"].upper()]
        net_switch_ok = android_network_manager.set_allowed_network_type(
            sim_slot=params["sim_slot"],
            mask=mask_enum,
            device_id=serial
        )
        if not net_switch_ok:
            err_msg = f"Step 4: 设置网络制式掩码 '{params['network_mask']}' 失败！"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
        
        # Step 5: Switch TX via mtk_tx.py
        print("\n--- Step 5: Setting TX Antenna Force ---")
        print("[*] Switching TX (reusing pre-connected device, logger control is skipped)...")
        tx_ok = mtk_tx.set_antenna_force(
            rat=params["rat"],
            band=params["band"],
            tx_state=params["tx_state"],
            rx_state=params["rx_state"] if "rx_state" in params else None,
            ttps_port=params["ttps_port"],
            device=device
        )
        if not tx_ok:
            err_msg = f"Step 5: 设置 TX 强迫发射天线失败 (rat={params['rat']}, band={params['band']}, tx_state={params['tx_state']})！"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
            
        # Step 6: Switch RX via mtk_rx.py
        print("\n--- Step 6: Setting RX Antenna Test ---")
        print("[*] Switching RX (reusing pre-connected device, logger control is skipped)...")
        
        # Map rx_mode to original integer scenario ID
        scenario_id = RX_MODES_MAP[params["rx_mode"].lower()]
        
        rx_net_type = "4g" if params["rat"].upper() in ("LTE", "LTE_TDD") else "nr"
        rx_ok = mtk_rx.run_antenna_rx_test(
            scenario_id=scenario_id,
            network_type=rx_net_type,
            control_logger=False,
            device=device
        )
        if not rx_ok:
            err_msg = f"Step 6: 设置 RX 接收分集测试失败 (mode={params['rx_mode']})！"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
            
    except Exception as e:
        err_msg = f"流程执行中发生异常: {e}"
        print(f"[ERROR] {err_msg}")
        return FlowResult(False, err_msg)
    finally:
        # Step 7: Stop log
        print("\n--- Step 7: Stopping MTK Logger ---")
        mtk_rx.control_mtk_logger("stop", device_id=serial)
    
    print("\n" + "="*70)
    if tx_ok and rx_ok:
        print("[SUCCESS] All steps in orchestration flow completed successfully!")
        return FlowResult(True, "")
    else:
        err_msg = "编排流程执行完毕，但存在未完全成功的步骤。"
        print(f"[WARNING] {err_msg}")
        return FlowResult(False, err_msg)

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
                        
    args = parser.parse_args()
    
    # Package into a parameters dictionary
    params = {
        "serial": args.serial,
        "rat": args.rat,
        "band": args.band,
        "tx_state": args.tx_state,
        "ttps_port": args.ttps_port,
        "sim_slot": args.sim_slot,
        "rx_mode": args.rx_mode
    }
    if args.rx_state is not None:
        params["rx_state"] = args.rx_state
        
    try:
        # Execute the main flow
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
