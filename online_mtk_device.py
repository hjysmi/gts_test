#----------------------------------------------------------------------
# Description:
#  Connect device, send AT command AT+ETXANT=4,3,3,5 and capture log
#----------------------------------------------------------------------

import mace
import time
import os

def main():
    try:
        # step1: Connect to device with auto database download
        print("Connecting to device via MACE...")
        device = mace.connect_device("auto", database="auto")
        print("Successfully connected!")
        
        # step2: Send AT command
        # at_command = r'AT+ETXANT=4,3,3,5'
        at_command = r'AT+ESBP?'
        print(f"Sending AT command: {at_command}")
        response = device.send_at_command(at_command)
        print(f"AT Command Response: {response}")
        
        # step3: Wait for a few seconds to capture modem logs
        capture_time = 5 # seconds
        print(f"Capturing modem logs for {capture_time} seconds...")
        time.sleep(capture_time)
        
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
