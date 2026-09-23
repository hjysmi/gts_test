"""
Antenna RX Test AT Command Runner.
Based on the scenarios defined in docs/antenna_rx_test_at_commands.html.
Uses MACE API as illustrated in mtk_atc_md.py.
"""

import argparse
import os
import re
import subprocess
import time
import mace

# Default configuration constants
DEFAULT_OUT_DIR = "."
DEFAULT_LOG_FILE = "antenna_test_log.elg"

# Test Scenarios definition based on docs/antenna_rx_test_at_commands.html
SCENARIOS = {
    1: {
        "name": "Combine_4Rx (All checked)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,3,15,3,15,0'
        ]
    },
    2: {
        "name": "Rx0 (Check 4 rx1)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,1,1,1'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,1,1,1,0'
        ]
    },
    3: {
        "name": "Rx1 (Check 4 rx2)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,2,2,2,2'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,2,2,2,2,0'
        ]
    },
    4: {
        "name": "Rx2 (Check rx1+rx3+rx1+rx3)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,4,1,4'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,4,1,4,0'
        ]
    },
    5: {
        "name": "Rx3 (Check rx1+rx4+rx1+rx4)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,8,1,8'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,8,1,8,0'
        ]
    },
    6: {
        "name": "Combine_2Rx",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,3,3,3',
            'AT+EGMC=1,"rx_path",1,0,3,3,3,3'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,3,3,3,3,0'
        ]
    }
}


def control_mtk_logger(action):
    """
    Control MTK logger via ADB commands.
    :param action: 'stop', 'start', or 'switch_usb'
    """
    commands = {
        "stop": [
            "adb", "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "stop", 
            "--ei", "cmd_target", "-1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ],
        "start": [
            "adb", "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "start", 
            "--ei", "cmd_target", "-1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ],
        "switch_usb": [
            "adb", "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "switch_modem_log_mode", 
            "--ei", "cmd_target", "1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ]
    }
    
    cmd = commands.get(action)
    if not cmd:
        print(f"[WARNING] Unknown MTK logger action: {action}")
        return
        
    print(f"[*] Executing MTK logger command for '{action}'...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"[+] MTK logger '{action}' command succeeded.")
        else:
            print(f"[WARNING] MTK logger '{action}' command returned exit code {result.returncode}.")
            print(f"  Stdout: {result.stdout.strip()}")
            print(f"  Stderr: {result.stderr.strip()}")
    except Exception as e:
        print(f"[ERROR] Exception running ADB command for MTK logger '{action}': {e}")
        
    print(f"[*] Sleeping 5 seconds after '{action}'...")
    time.sleep(5)


def connect_to_device(device_id="auto", database="auto"):
    """
    Connect to MACE device.
    """
    print(f"[*] Connecting to device via MACE (device={device_id}, database={database})...")
    try:
        device = mace.connect_device(device_id, database=database)
        print("[+] Successfully connected to MACE device!")
        return device
    except Exception as e:
        print(f"[ERROR] Failed to connect to device: {e}")
        raise


def send_and_get_at_response(device, at_command, timeout=5.0):
    """
    Sends an AT command using MACE and captures its full exact response from the modem.
    """
    # 1. Create a subscription itemset on the device
    itemset = mace.create_itemset(device)
    
    # 2. Subscribe to AT_TX responses from the modem
    itemset.subscribe_sys(r'AT_TX')
    
    # 3. Send the AT command
    print(f"[*] Sending AT command: {at_command}")
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
            clean_line = re.sub(r'^\[AT_TX[^\]]*\]', '', msg).strip()
            if clean_line:
                response_lines.append(clean_line)
                if clean_line in ('OK', 'ERROR'):
                    break
        else:
            time.sleep(0.05)
            
    return response_lines


def save_device_logs(device, out_dir=DEFAULT_OUT_DIR, filename=DEFAULT_LOG_FILE):
    """
    Save captured modem logs to .elg file.
    """
    try:
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
            
        save_path = os.path.join(out_dir, filename)
        print(f"[*] Saving log to: {save_path}")
        device.save(save_path)
        print("[+] Log saved successfully!")
        return save_path
    except Exception as e:
        print(f"[ERROR] Failed to save device logs: {e}")
        return None


def run_antenna_rx_test(scenario_id, network_type, log_filename=DEFAULT_LOG_FILE, out_dir=DEFAULT_OUT_DIR, control_logger=True, device=None):
    """
    Run full Antenna RX Test AT command flow for a given scenario and network type.
    """
    if scenario_id not in SCENARIOS:
        print(f"[ERROR] Invalid scenario ID: {scenario_id}")
        return False
        
    net_type = network_type.lower()
    if net_type not in ["4g", "nr"]:
        print(f"[ERROR] Invalid network type: {network_type}. Must be '4g' or 'nr'.")
        return False
        
    scenario = SCENARIOS[scenario_id]
    commands = scenario[net_type]
    
    print("\n" + "="*60)
    print(f"Antenna RX Test Execution Plan:")
    print(f"  Scenario: {scenario['name']}")
    print(f"  Network : {net_type.upper()}")
    print(f"  Commands: {', '.join(commands)}")
    print("="*60 + "\n")
    
    success = True
    try:
        # 1. MTK logger preparation (stop -> switch to USB -> start)
        if control_logger:
            control_mtk_logger("stop")
            control_mtk_logger("switch_usb")
            control_mtk_logger("start")

        # 2. Connect device
        if device is None:
            device = connect_to_device("auto", database="auto")
        else:
            print("[*] Reusing pre-connected MACE device for RX switching.")
        
        # 3. Send commands sequentially
        for idx, cmd in enumerate(commands):
            print(f"\n[*] [Step {idx+1}/{len(commands)}] Sending: {cmd}")
            response_lines = send_and_get_at_response(device, cmd)
            
            # Print response
            print("-"*50)
            print(f"Modem Response:")
            if response_lines:
                for line in response_lines:
                    print(f"  {line}")
                if "ERROR" in response_lines:
                    print(f"[WARNING] Step {idx+1} failed with ERROR response.")
                    success = False
            else:
                print("  (No response / timeout)")
                success = False
            print("-"*50)
            
            # For 4G 2-step execution, insert a small pause between commands to allow the modem to stabilize
            if len(commands) > 1 and idx < len(commands) - 1:
                print("[*] Stabilizing modem path, sleeping 1 second...")
                time.sleep(1.0)
                
        # 4. Save device logs
        if device:
            save_device_logs(device, out_dir=out_dir, filename=log_filename)
            
    except Exception as e:
        print(f"[ERROR] Antenna RX Test flow encountered an exception: {e}")
        success = False
    finally:
        # 5. Clean up logger
        if control_logger:
            print("[*] Performing cleanup...")
            control_mtk_logger("stop")
        
    return success


def main():
    parser = argparse.ArgumentParser(description="Antenna RX Test Scenario Executor")
    parser.add_argument(
        "--scenario", 
        type=int, 
        choices=[1, 2, 3, 4, 5, 6], 
        required=True, 
        help="Scenario ID (1: Combine_4Rx, 2: Rx0, 3: Rx1, 4: Rx2, 5: Rx3, 6: Combine_2Rx)"
    )
    parser.add_argument(
        "--network", 
        type=str, 
        choices=["4g", "LTE", "lte", "nr", "5g", "5G"], 
        required=True, 
        help="Network type (4g/lte or nr/5g)"
    )
    parser.add_argument(
        "--out-dir", 
        type=str, 
        default=DEFAULT_OUT_DIR, 
        help=f"Directory to save capture logs (default: {DEFAULT_OUT_DIR})"
    )
    parser.add_argument(
        "--log-file", 
        type=str, 
        default=DEFAULT_LOG_FILE, 
        help=f"Filename of output log (default: {DEFAULT_LOG_FILE})"
    )
    
    args = parser.parse_args()
    
    # Normalize network input
    network = "4g" if args.network.lower() in ["4g", "lte"] else "nr"
    
    success = run_antenna_rx_test(
        scenario_id=args.scenario,
        network_type=network,
        log_filename=args.log_file,
        out_dir=args.out_dir
    )
    
    if success:
        print("\n[+] Antenna RX Test completed successfully!")
    else:
        print("\n[-] Antenna RX Test failed or completed with warnings.")


if __name__ == "__main__":
    """
   1    # 测试 4G (LTE) Combine 场景 (场景 1)
   2    python mtk_rx_test.py --scenario 1 --network 4g
   3
   4    # 测试 NR (5G) Rx0 场景 (场景 2)
   5    python mtk_rx_test.py --scenario 2 --network nr
   6
   7    # 自定义日志输出路径和文件名
   8    python mtk_rx_test.py --scenario 3 --network 4g --out-dir D:\test_out --log-file my_test.elg
    """
    main()
