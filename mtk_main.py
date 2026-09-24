import sys
import os
import argparse
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

    required_keys = ["rat", "band", "tx_state", "ttps_port", "sim_slot", "rx_mode"]
    for key in required_keys:
        if key not in params:
            raise ValueError(f"Missing required parameter key: '{key}'")
            
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
        print(f"\n[PARAM ERROR] Parameter validation failed: {e}")
        sys.exit(1)

    # Step 1: Stop log
    print("\n--- Step 1: Stopping MTK Logger ---")
    mtk_rx.control_mtk_logger("stop")
    
    # Step 2: Switch modem mode to USB mode
    print("\n--- Step 2: Setting Modem Logging Mode to USB ---")
    mtk_rx.control_mtk_logger("switch_usb")
    
    # Step 3: Start log
    print("\n--- Step 3: Starting MTK Logger ---")
    mtk_rx.control_mtk_logger("start")
    
    device = None
    tx_ok = False
    rx_ok = False
    
    try:
        # Connect to MACE ONCE (before Step 4 Network Type Switch)
        print("\n--- Establishing Connection ---")
        print("[*] Connecting to MACE device ONCE for shared use in network/TX/RX switching...")
        device = mtk_atc_md.connect_to_device("auto", database="auto")
        
        # Step 4: Switch network type via android_network_manager
        print("\n--- Step 4: Switching Network Type ---")
        mask_enum = android_network_manager.NetworkMask[params["network_mask"].upper()]
        net_switch_ok = android_network_manager.set_allowed_network_type(
            sim_slot=params["sim_slot"],
            mask=mask_enum
        )
        if not net_switch_ok:
            print("[ERROR] Failed to switch network type. Aborting flow.")
            return False
        
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
            print("[ERROR] TX Antenna Force configuration failed. Aborting flow.")
            return False
            
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
            print("[ERROR] RX Antenna Test configuration failed.")
            
    except Exception as e:
        print(f"[ERROR] Session interaction with MACE failed: {e}")
    finally:
        # Step 7: Stop log
        print("\n--- Step 7: Stopping MTK Logger ---")
        mtk_rx.control_mtk_logger("stop")
    
    print("\n" + "="*70)
    if tx_ok and rx_ok:
        print("[SUCCESS] All steps in orchestration flow completed successfully!")
        return True
    else:
        print("[WARNING] Orchestration flow completed with warnings or step failures.")
        return False

# Backward-compatible alias for module integration
run_orchestration_flow = run_mtk_flow

def main():
    parser = argparse.ArgumentParser(description="MTK End-to-End Antenna Orchestration Script")
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
        run_mtk_flow(params)
    except Exception as e:
        print(f"\n[FATAL ERROR] Flow execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
