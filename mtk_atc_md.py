#----------------------------------------------------------------------
# Description:
#  Connect device, send AT command and print exact response from the modem.
#----------------------------------------------------------------------

import mace
import time
import os
import re
import subprocess

# Default configuration constants
DEFAULT_OUT_DIR = r"D:\share_179\0519\bank_prod\out"
DEFAULT_LOG_FILE = "modem_log.elg"


def control_mtk_logger(action, device_id=None):
    """
    Control MTK logger via ADB commands.
    :param action: 'stop', 'start', or 'switch_usb'
    :param device_id: Optional ADB serial number targeting a specific device
    """
    base_cmd = ["adb"]
    if device_id:
        base_cmd.extend(["-s", str(device_id)])

    commands = {
        "stop": base_cmd + [
            "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "stop", 
            "--ei", "cmd_target", "-1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ],
        "start": base_cmd + [
            "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "start", 
            "--ei", "cmd_target", "-1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ],
        "switch_usb": base_cmd + [
            "shell", "am", "broadcast", 
            "-a", "com.debug.loggerui.ADB_CMD", 
            "-e", "cmd_name", "switch_modem_log_mode", 
            "--ei", "cmd_target", "1", 
            "-n", "com.debug.loggerui/.framework.LogReceiver"
        ]
    }
    
    cmd = commands.get(action)
    if not cmd:
        print(f"[WARNING] Unknown MTK logger action: {action}")
        return False
        
    print(f"[*] Executing MTK logger command for '{action}'...")
    success = False
    try:
        # We run the command and wait for it. We don't raise an exception 
        # to prevent blocking the entire flow if ADB/device is not ready,
        # but we print the outcome.
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"[+] MTK logger '{action}' command succeeded.")
            success = True
        else:
            print(f"[WARNING] MTK logger '{action}' command returned exit code {result.returncode}.")
            print(f"  Stdout: {result.stdout.strip()}")
            print(f"  Stderr: {result.stderr.strip()}")
    except Exception as e:
        print(f"[ERROR] Exception running ADB command for MTK logger '{action}': {e}")
        
    # Wait for 5 seconds as requested to ensure the command has finished processing
    # on the device before executing the next step.
    print(f"[*] Sleeping 5 seconds after '{action}'...")
    time.sleep(5)
    return success



def connect_to_device(device_id="auto", database="auto"):
    """
    连接到 MACE 调试设备
    (Connect to device via MACE)
    :param device_id: 设备标识符 (e.g., "auto" 或 ADB 序列号)
    :param database: 数据库类型 (e.g., "auto")
    :return: connected device instance
    """
    # MACE requires "auto" or a specific COM port. If an ADB serial is passed, use "auto".
    mace_target = "auto" if not device_id or not str(device_id).upper().startswith("COM") else device_id
    print(f"[*] Connecting to device via MACE (device={mace_target}, database={database})...")
    try:
        device = mace.connect_device(mace_target, database=database)
        print("[+] Successfully connected to MACE device!")
        return device
    except Exception as e:
        print(f"[ERROR] Failed to connect to device: {e}")
        raise


def send_and_get_at_response(device, at_command, timeout=5.0):
    """
    向调制解调器发送 AT 命令并捕获其完整且精准的响应
    (Sends an AT command using MACE and captures its full exact response from the modem)
    :param device: 已连接的 MACE 设备实例
    :param at_command: 待发送的 AT 命令
    :param timeout: 超时时间（秒）
    :return: 干净的响应行列表 (e.g. ['+ESBP: 0,9,...', 'OK'])
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


def parse_and_print_sbp(response_lines):
    """
    解析并美化打印 AT 响应中的 SBP 结构化信息
    (Parse and print SBP info from AT response lines)
    :param response_lines: 响应行列表
    :return: 解析后的字典 {sbp_id, sim_sbp_id, sbp_data}，若未找到或未解析成功则返回 None
    """
    if not response_lines:
        print("  (No response lines received from the modem)")
        return None

    print("\n" + "="*50)
    print("AT Command Response Received:")
    print("="*50)
    for line in response_lines:
        print(f"  {line}")

    esbp_raw = None
    for line in response_lines:
        if line.startswith("+ESBP:"):
            esbp_raw = line
            break
    
    parsed_info = None
    if esbp_raw:
        match = re.search(r'\+ESBP:\s*([^,\s]+)\s*,\s*([^,\s]+)\s*,\s*(.*)', esbp_raw)
        if match:
            sbp_id = match.group(1).strip()
            sim_sbp_id = match.group(2).strip()
            sbp_data = match.group(3).strip().strip('"')
            parsed_info = {
                "sbp_id": sbp_id,
                "sim_sbp_id": sim_sbp_id,
                "sbp_data": sbp_data
            }
            print("-"*50)
            print("Parsed SBP Information:")
            print(f"  Device SBP ID : {sbp_id}")
            print(f"  SIM SBP ID    : {sim_sbp_id}")
            print(f"  SBP Data      : {sbp_data}")
    print("="*50 + "\n")
    return parsed_info


def save_device_logs(device, out_dir=DEFAULT_OUT_DIR, filename=DEFAULT_LOG_FILE):
    """
    将当前捕获的调制解调器日志保存为 .elg 文件
    (Save captured modem logs to .elg file)
    :param device: 已连接的 MACE 设备实例
    :param out_dir: 输出文件夹路径
    :param filename: 文件名称
    :return: 完整的保存路径，若失败则返回 None
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


def run_at_command_flow(at_command=r'AT+ESBP?', log_filename=DEFAULT_LOG_FILE, out_dir=DEFAULT_OUT_DIR):
    """
    一键运行全流程：连接设备、发送 AT 指令、解析并打印响应、保存日志
    (Run full AT command flow: connect, send command, parse response, save logs)
    :param at_command: 要发送的 AT 指令
    :param log_filename: 日志文件名
    :param out_dir: 日志输出文件夹
    :return: (response_lines, parsed_info) 元组
    """
    device = None
    response_lines = []
    parsed_info = None
    try:
        # 0. MTK logger preparation (stop -> switch to USB -> start)
        control_mtk_logger("stop")
        control_mtk_logger("switch_usb")
        control_mtk_logger("start")

        # 1. 连接设备
        device = connect_to_device("auto", database="auto")
        
        # 2. 发送 AT 命令行并等待回复
        response_lines = send_and_get_at_response(device, at_command)
        
        # 3. 打印并解析 SBP 数据
        parsed_info = parse_and_print_sbp(response_lines)
        
        # 4. 保存捕获的日志文件
        save_device_logs(device, out_dir=out_dir, filename=log_filename)
        
    except Exception as e:
        print(f"[ERROR] AT command flow failed: {e}")
    finally:
        # 5. MTK logger cleanup (stop log)
        control_mtk_logger("stop")
        
    return response_lines, parsed_info


def main():
    # 示例默认执行写操作流程，也可以根据需要直接调用子函数
    # at_command = r'AT+ESBP=16,"310","120"'
    at_command = r'AT+ESBP?'
    run_at_command_flow(at_command=at_command)


if __name__ == "__main__":
    main()
