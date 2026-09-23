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
import qc_efs_tx
import qc_lte_rx
import android_network_manager

# Allowed values for validation
ALLOWED_RATS = ["LTE", "LTE_ONLY", "NR", "NR_ONLY"]
ALLOWED_TX_VALUES = ["tx0", "tx1", "tx2", "tx3"]
ALLOWED_ANT_VALUES = ["0", "00", "1", "11", "2", "22", "3", "33", "default", "FF"]
ALLOWED_RX_MODES = ["combine", "rx0", "rx1", "rx2", "rx3"]

def validate_params(params):
    """
    Validate the input configuration parameter dictionary.
    Raises ValueError if validation fails.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters must be passed as a dictionary class.")
        
    required_keys = ["serial", "qcn_file", "rat", "tx", "ant_value", "network_mask"]
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
    tx = str(params["tx"]).lower()
    if tx not in ALLOWED_TX_VALUES:
        raise ValueError(f"Invalid 'tx': '{params['tx']}'. Must be one of: {ALLOWED_TX_VALUES}")
        
    # 5. Validate ANT value
    ant_value = str(params["ant_value"]).lower()
    if ant_value not in ALLOWED_ANT_VALUES:
        raise ValueError(f"Invalid 'ant_value': '{params['ant_value']}'. Must be one of: {ALLOWED_ANT_VALUES}")
        
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

def run_qc_flow(params):
    """
    Run the full end-to-end Qualcomm testing orchestration flow:
    1. Write and Query NV73841 & NV73971.
    2. Change Network Type.
    3. Configure TX Antenna (ASDiv).
    4. Configure LTE RX Path (skipped in NR mode).
    5. Restore XQCN backup (moved to last step).
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
    ant_value = str(params["ant_value"])
    sim_slot = params.get("sim_slot", 0)
    network_mask = params["network_mask"].upper()
    
    print("\n" + "="*70)
    print("STARTING QUALCOMM ANTENNA TESTING ORCHESTRATION FLOW")
    print("="*70)
    
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
        
    # Step 3: Switch TX (ASDiv Config) via qc_efs_tx
    print("\n--- Step 3: Configuring TX Antenna (ASDiv) ---")
    print(f"[*] Setting ASDiv config path to: {ant_value}")
    tx_ok = qc_efs_tx.switch_asdiv_config(value=ant_value, client_name="QcOrchestrationASDiv")
    if not tx_ok:
        print("[WARNING] ASDiv config write returned False.")
        
    # Step 4: Switch LTE RX Path via qc_lte_rx
    print("\n--- Step 4: Configuring LTE RX Paths ---")
    if rat in ["NR", "NR_ONLY"]:
        print("[INFO] Target network mode is NR (5G). SKIPPING Step 4 (LTE RX selection).")
    else:
        rx_mode = params["rx_mode"].lower()
        print(f"[*] Setting LTE Rx selection to mode: '{rx_mode}'")
        rx_ok = qc_lte_rx.switch_lte_rx(mode=rx_mode, client_name="QcOrchestrationLteRx")
        if not rx_ok:
            print("[WARNING] LTE Rx path selection returned False.")
            
    # Step 5: Restore XQCN (moved to last step)
    print("\n--- Step 5: Restoring QCN/XQCN Backup ---")
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
    parser.add_argument("--tx", required=True, choices=["tx0", "tx1", "tx2", "tx3"], 
                        help="TX antenna target: tx0 (0), tx1 (17), tx2 (34), tx3 (51)", type=str.lower)
    parser.add_argument("--ant-value", required=True, choices=["0", "00", "1", "11", "2", "22", "3", "33", "default", "FF"], 
                        help="ASDiv TX antenna override target selection")
    parser.add_argument("--rx-mode", choices=["combine", "rx0", "rx1", "rx2", "rx3"], 
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
        "ant_value": args.ant_value,
        "sim_slot": args.sim_slot,
        "network_mask": args.network_mask
    }
    if args.rx_mode is not None:
        params["rx_mode"] = args.rx_mode
        
    try:
        # Execute the main orchestrated flow
        run_qc_flow(params)
    except Exception as e:
        print(f"\n[FATAL ERROR] Flow execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
