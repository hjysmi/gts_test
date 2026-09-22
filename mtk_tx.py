import argparse
import sys
import mtk_atc_md

def set_antenna_force(rat, band, tx_state, rx_state, ttps_port):
    """
    Generate and send the AT command for Antenna Force via TTPS.
    """
    tas_mode = 1  # 1 means Enable
    
    if rat.upper() == 'LTE':
        # LTE (FDD) uses tx_state for both TX and RX path fields in the lte_force_ttps command
        at_cmd = f'AT+EGMC=1,"lte_force_ttps",{tas_mode},{tx_state},{tx_state},{ttps_port},{band}'
    elif rat.upper() in ('LTE_TDD', 'LTE TDD'):
        # LTE TDD uses tx_state and rx_state
        if rx_state is None:
            print("[ERROR] --rx-state is required for LTE TDD")
            sys.exit(1)
        at_cmd = f'AT+EGMC=1,"lte_force_ttps",{tas_mode},{tx_state},{rx_state},{ttps_port},{band}'
    elif rat.upper() == 'NR':
        # NR uses NR_force_TTPS and takes both tx_state and rx_state
        if rx_state is None:
            print("[ERROR] --rx-state is required for NR")
            sys.exit(1)
        at_cmd = f'AT+EGMC=1,"NR_force_TTPS",{tas_mode},{tx_state},{rx_state},{ttps_port},{band}'
    else:
        print(f"[ERROR] Unsupported RAT: {rat}")
        sys.exit(1)
        
    print(f"[*] Generated AT Command: {at_cmd}")
    
    device = None
    try:
        device = mtk_atc_md.connect_to_device("auto", database="auto")
        response_lines = mtk_atc_md.send_and_get_at_response(device, at_cmd)
        
        print("\n" + "="*50)
        print("AT Command Response Received:")
        print("="*50)
        success = False
        for line in response_lines:
            print(f"  {line}")
            if "OK" in line or "SUCCESS" in line.upper():
                success = True
        print("="*50 + "\n")
        
        if success:
            print("[+] Success: Antenna Force set successfully.")
        else:
            print("[-] Warning: Did not receive a clear success message.")
            
    except Exception as e:
        print(f"[ERROR] Failed to execute Antenna Force: {e}")

def main():
    parser = argparse.ArgumentParser(description="MTK Antenna Force Configuration")
    parser.add_argument("--rat", required=True, choices=["LTE", "LTE_TDD", "LTE TDD", "NR"], 
                        help="TAS Rat: LTE, LTE_TDD, or NR", type=str.upper)
    parser.add_argument("--band", required=True, type=int, help="TAS band to test")
    parser.add_argument("--tx-state", required=True, type=int, help="Tx TAS State (e.g., 0 to 23)")
    parser.add_argument("--rx-state", type=int, help="Rx TAS State (Required for LTE_TDD and NR)")
    parser.add_argument("--ttps-port", required=True, type=int, help="TTPS TX port (e.g., 0 or 1)")
    
    args = parser.parse_args()
    
    set_antenna_force(args.rat, args.band, args.tx_state, args.rx_state, args.ttps_port)

if __name__ == "__main__":
    main()
