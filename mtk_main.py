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

# Mapping RX scenario names to their original integer scenario IDs
RX_SCENARIOS_MAP = {
    "COMBINE": 1,
    "RX0": 2,
    "RX1": 3,
    "RX2": 4,
    "RX3": 5
}

def validate_params(params):
    """
    Validate the configuration parameter dictionary.
    Raises ValueError if validation fails.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters must be passed as a dictionary class.")
        
    required_keys = ["rat", "band", "tx_state", "ttps_port", "sim_slot", "network_mask", "rx_scenario"]
    for key in required_keys:
        if key not in params:
            raise ValueError(f"Missing required parameter key: '{key}'")
            
    # Validate RAT
    rat = params["rat"].upper() if isinstance(params["rat"], str) else ""
    if rat not in ["LTE", "LTE_TDD", "NR"]:
        raise ValueError(f"Invalid RAT: '{params['rat']}'. Must be 'LTE', 'LTE_TDD', or 'NR'.")
        
    # Validate Band and its alignment with RAT
    band = params["band"]
    if not isinstance(band, int) or band <= 0:
        raise ValueError(f"Invalid band: '{band}'. Must be a positive integer.")
        
    if rat == "LTE":
        # Must be LTE FDD
        if band not in LTE_FDD_BANDS:
            if band in LTE_TDD_BANDS:
                raise ValueError(f"Invalid configuration: Band {band} is an LTE TDD band, but RAT is set to LTE (FDD).")
            else:
                raise ValueError(f"Invalid configuration: Band {band} is not a recognized LTE FDD band. LTE FDD bands: {sorted(list(LTE_FDD_BANDS))}")
                
        # For LTE FDD, Rx TAS State must NOT be set
        if params.get("rx_state") is not None:
            raise ValueError(f"Invalid configuration: 'rx_state' (Rx TAS State) was set to {params['rx_state']}, but Rx TAS State must not be set for LTE FDD.")
            
    elif rat == "LTE_TDD":
        # Must be LTE TDD
        if band not in LTE_TDD_BANDS:
            if band in LTE_FDD_BANDS:
                raise ValueError(f"Invalid configuration: Band {band} is an LTE FDD band, but RAT is set to LTE_TDD.")
            else:
                raise ValueError(f"Invalid configuration: Band {band} is not a recognized LTE TDD band. LTE TDD bands: {sorted(list(LTE_TDD_BANDS))}")
                
        # For LTE TDD, Rx TAS State is required
        if params.get("rx_state") is None:
            raise ValueError("Invalid configuration: 'rx_state' (Rx TAS State) is required when RAT is LTE_TDD.")
            
    elif rat == "NR":
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
        
    # Validate Network Mask
    mask_str = params["network_mask"].upper() if isinstance(params["network_mask"], str) else ""
    try:
        android_network_manager.NetworkMask[mask_str]
    except KeyError:
        raise ValueError(f"Invalid 'network_mask': '{params['network_mask']}'. Must be one of: "
                         f"{[m.name for m in android_network_manager.NetworkMask]}")
                         
    # Validate RX Scenario Name
    rx_scenario = params["rx_scenario"].upper() if isinstance(params["rx_scenario"], str) else ""
    if rx_scenario not in RX_SCENARIOS_MAP:
        raise ValueError(f"Invalid 'rx_scenario': '{params['rx_scenario']}'. Must be one of "
                         f"{list(RX_SCENARIOS_MAP.keys())} or matching casing: "
                         f"['Combine', 'Rx0', 'Rx1', 'Rx2', 'Rx3'].")

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
        
        # Map scenario name to original integer ID
        scenario_id = RX_SCENARIOS_MAP[params["rx_scenario"].upper()]
        
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

def main():
    parser = argparse.ArgumentParser(description="MTK End-to-End Antenna Orchestration Script")
    parser.add_argument("--rat", required=True, choices=["LTE", "LTE_TDD", "NR"], 
                        help="RAT selection: LTE (FDD), LTE_TDD, or NR", type=str.upper)
    parser.add_argument("--band", required=True, type=int, help="Band number")
    parser.add_argument("--tx-state", required=True, type=int, help="Tx TAS State (0-23, or 255)")
    parser.add_argument("--rx-state", type=int, help="Rx TAS State (0-23, or 255). Required for LTE_TDD and NR.")
    parser.add_argument("--ttps-port", required=True, type=int, help="TTPS TX port (0 or 1)")
    parser.add_argument("--sim-slot", required=True, type=int, choices=[0, 1], help="SIM Slot: 0 for SIM1, 1 for SIM2")
    parser.add_argument("--network-mask", required=True, 
                        choices=["LTE_ONLY", "NR_ONLY", "NR_LTE", "DEFAULT"], 
                        help="Network type mask from android_network_manager")
    parser.add_argument("--rx-scenario", required=True, 
                        choices=["Combine", "Rx0", "Rx1", "Rx2", "Rx3"], 
                        help="RX Scenario Name: Combine, Rx0, Rx1, Rx2, or Rx3")
                        
    args = parser.parse_args()
    
    # Package into a parameters dictionary
    params = {
        "rat": args.rat,
        "band": args.band,
        "tx_state": args.tx_state,
        "ttps_port": args.ttps_port,
        "sim_slot": args.sim_slot,
        "network_mask": args.network_mask,
        "rx_scenario": args.rx_scenario
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
