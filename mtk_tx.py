import sys
import mtk_atc_md

def set_antenna_force(rat, band, tx_state, rx_state, ttps_port, device=None):
    """
    Generate and send the AT command for Antenna Force via TTPS.
    Does NOT control the MTK logger.
    :param device: Optional pre-connected MACE device instance to avoid re-connection.
    """
    tas_mode = 1  # 1 means Enable
    
    if rat.upper() == 'LTE':
        # LTE (FDD) uses tx_state for both TX and RX path fields in the lte_force_ttps command
        at_cmd = f'AT+EGMC=1,"lte_force_ttps",{tas_mode},{tx_state},{tx_state},{ttps_port},{band}'
    elif rat.upper() in ('LTE_TDD', 'LTE TDD'):
        # LTE TDD uses tx_state and rx_state
        if rx_state is None:
            print("[ERROR] rx_state is required for LTE TDD")
            return False
        at_cmd = f'AT+EGMC=1,"lte_force_ttps",{tas_mode},{tx_state},{rx_state},{ttps_port},{band}'
    elif rat.upper() == 'NR':
        # NR uses NR_force_TTPS and takes both tx_state and rx_state
        if rx_state is None:
            print("[ERROR] rx_state is required for NR")
            return False
        at_cmd = f'AT+EGMC=1,"NR_force_TTPS",{tas_mode},{tx_state},{rx_state},{ttps_port},{band}'
    else:
        print(f"[ERROR] Unsupported RAT: {rat}")
        return False
        
    print(f"[*] Generated AT Command for TX: {at_cmd}")
    
    try:
        # Reuse or connect
        if device is None:
            device = mtk_atc_md.connect_to_device("auto", database="auto")
        else:
            print("[*] Reusing pre-connected MACE device for TX switching.")
            
        response_lines = mtk_atc_md.send_and_get_at_response(device, at_cmd)
        
        print("\n" + "="*50)
        print("AT Command Response Received (TX):")
        print("="*50)
        success = False
        for line in response_lines:
            print(f"  {line}")
            if "OK" in line or "SUCCESS" in line.upper():
                success = True
        print("="*50 + "\n")
        
        return success
    except Exception as e:
        print(f"[ERROR] Failed to execute Antenna Force TX: {e}")
        return False
