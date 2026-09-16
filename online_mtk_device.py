#----------------------------------------------------------------------
# Description:
#  Connect device, send AT command and print exact response from the modem.
#----------------------------------------------------------------------

import mace
import time
import os
import re

def send_and_get_at_response(device, at_command, timeout=5.0):
    """
    Sends an AT command using MACE and captures its full exact response from the modem.
    Returns a list of clean response lines (e.g. ['+ESBP: 0,9,...', 'OK'] or ['ERROR']).
    """
    # 1. Create a subscription itemset on the device
    itemset = mace.create_itemset(device)
    
    # 2. Subscribe to AT_TX responses from the modem
    itemset.subscribe_sys(r'AT_TX')
    
    # 3. Send the AT command
    print(f"Sending AT command: {at_command}")
    sent_success = device.send_at_command(at_command)
    if not sent_success:
        print("[WARNING] MACE returned False for sending the command (it might not have reached the device).")
        
    # 4. Collect response lines
    response_lines = []
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        item = itemset.get_next_item(100) # check queue every 100ms
        if item:
            msg = item.message
            # Strip the channel prefix '[AT_TX p99,ch4]' or similar
            clean_line = re.sub(r'^\[AT_TX[^\]]*\]', '', msg).strip()
            if clean_line:
                response_lines.append(clean_line)
                # If we received the final status line, we can stop waiting
                if clean_line in ('OK', 'ERROR'):
                    break
        else:
            # Small sleep to prevent busy waiting
            time.sleep(0.05)
            
    return response_lines

def main():
    try:
        # step1: Connect to device with auto database download
        print("Connecting to device via MACE...")
        device = mace.connect_device("auto", database="auto")
        print("Successfully connected!")
        
        # step2: Send AT command and get exact response
        # To run query: use 'AT+ESBP?'
        # To run write: use 'AT+ESBP=16,"440","10"' (or similar)
        at_command = r'AT+ESBP?'
        
        response_lines = send_and_get_at_response(device, at_command)
        
        # step3: Print and parse response
        print("\n" + "="*50)
        print("AT Command Response Received:")
        print("="*50)
        if response_lines:
            for line in response_lines:
                print(f"  {line}")
                
            # If the response contains +ESBP info, let's parse and show details nicely
            esbp_raw = None
            for line in response_lines:
                if line.startswith("+ESBP:"):
                    esbp_raw = line
                    break
            
            if esbp_raw:
                match = re.search(r'\+ESBP:\s*([^,\s]+)\s*,\s*([^,\s]+)\s*,\s*(.*)', esbp_raw)
                if match:
                    sbp_id = match.group(1).strip()
                    sim_sbp_id = match.group(2).strip()
                    sbp_data = match.group(3).strip().strip('"')
                    print("-"*50)
                    print("Parsed SBP Information:")
                    print(f"  Device SBP ID : {sbp_id}")
                    print(f"  SIM SBP ID    : {sim_sbp_id}")
                    print(f"  SBP Data      : {sbp_data}")
        else:
            print("  (No response lines received from the modem)")
        print("="*50 + "\n")
        
        # step4: Save the captured logs to an .elg file
        out_dir = r"D:\share_179\0519\bank_prod\out"
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
            
        save_path = os.path.join(out_dir, "modem_log.elg")
        print(f"Saving log to: {save_path}")
        device.save(save_path)
        print("Log saved successfully!")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
