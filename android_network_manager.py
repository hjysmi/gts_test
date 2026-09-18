#----------------------------------------------------------------------
# Description:
#  Manage Android network types (LTE Only, NR Only, NR | LTE, Default)
#  via ADB shell cmd phone commands for both SIM 1 and SIM 2.
#----------------------------------------------------------------------

import subprocess
import sys
from enum import Enum
from typing import Tuple, List, Optional

class NetworkMask(Enum):
    """
    Enum representing different allowed network type masks.
    """
    LTE_ONLY = "01000001000000000000"       # 仅限 4G
    NR_ONLY = "10000000000000000000"        # 仅限 5G
    NR_LTE = "11000001000000000000"         # 5G/4G 自动，禁用 2G/3G
    DEFAULT = "11001111101111111111"        # 恢复默认设置：全制式自动：5G/4G/3G/2G 自动


def parse_network_tech_string(tech_string: str) -> str:
    """
    Parse the raw technology list returned by ADB and map it to a user-friendly config.
    
    :param tech_string: Raw pipe-separated technology string (e.g. "LTE|LTE_CA|NR")
    :return: Friendly configuration name (e.g. "NR_LTE")
    """
    techs = {t.strip() for t in tech_string.split("|") if t.strip()}
    
    # Define legacy technologies that indicate default multi-mode behavior (2G/3G)
    legacy_techs = {"GPRS", "EDGE", "UMTS", "GSM", "CDMA", "1xRTT", "EvDo", "HSDPA", "HSUPA", "HSPA", "HSPA+"}
    has_legacy = bool(techs & legacy_techs or any("CDMA" in t or "HSPA" in t for t in techs))
    
    has_nr = "NR" in techs
    has_lte = "LTE" in techs or "LTE_CA" in techs
    
    if has_nr and has_lte and not has_legacy:
        return "NR_LTE (5G / 4G Automatic, 2G/3G Disabled)"
    elif has_lte and not has_nr and not has_legacy:
        return "LTE_ONLY (4G Only)"
    elif has_nr and not has_lte and not has_legacy:
        return "NR_ONLY (5G Only)"
    elif has_legacy:
        return "DEFAULT (5G/4G/3G/2G Automatic)"
    
    return "UNKNOWN"


def run_adb_command(cmd_args: List[str]) -> Tuple[bool, str, str]:
    """
    Helper to run an ADB command safely using subprocess.
    
    :param cmd_args: List of command arguments, starting with 'adb'
    :return: A tuple of (is_success, stdout_string, stderr_string)
    """
    try:
        result = subprocess.run(cmd_args, capture_output=True, text=True, check=False)
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        
        if result.returncode == 0:
            return True, stdout, stderr
        else:
            return False, stdout, stderr
    except FileNotFoundError:
        return False, "", "ADB executable not found. Please verify that Android Platform Tools is installed and 'adb' is in your PATH."
    except Exception as e:
        return False, "", f"Exception occurred while running ADB: {str(e)}"


def set_allowed_network_type(sim_slot: int, mask: NetworkMask, device_id: Optional[str] = None) -> bool:
    """
    Set allowed network types for user on a specific SIM slot.
    
    :param sim_slot: SIM slot index (0 for SIM 1, 1 for SIM 2)
    :param mask: NetworkMask Enum indicating the desired network configuration
    :param device_id: Optional ADB device serial number for targeting a specific device
    :return: True if successful, False otherwise
    """
    if sim_slot not in (0, 1):
        print(f"[ERROR] Invalid SIM slot: {sim_slot}. Must be 0 (SIM 1) or 1 (SIM 2).")
        return False
        
    if not isinstance(mask, NetworkMask):
        print(f"[ERROR] Invalid mask: {mask}. Must be an instance of NetworkMask enum.")
        return False
        
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
    
    cmd.extend([
        "shell", "cmd", "phone", "set-allowed-network-types-for-users",
        "-s", str(sim_slot), mask.value
    ])
    
    print(f"[*] Setting network type for SIM {sim_slot + 1} to {mask.name} (Mask: {mask.value})...")
    print(f"[*] Command: {' '.join(cmd)}")
    
    success, stdout, stderr = run_adb_command(cmd)
    if success:
        print(f"[+] Successfully set network type for SIM {sim_slot + 1} to {mask.name}.")
        if stdout:
            print(f"  Output: {stdout}")
        return True
    else:
        print(f"[ERROR] Failed to set network type for SIM {sim_slot + 1}.")
        if stderr:
            print(f"  Error: {stderr}")
        if stdout:
            print(f"  Output: {stdout}")
        return False


def get_allowed_network_type(sim_slot: int, device_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Query the current allowed network types for a specific SIM slot.
    
    :param sim_slot: SIM slot index (0 for SIM 1, 1 for SIM 2)
    :param device_id: Optional ADB device serial number for targeting a specific device
    :return: Tuple of (success_boolean, status_string_or_error_message)
    """
    if sim_slot not in (0, 1):
        err_msg = f"Invalid SIM slot: {sim_slot}. Must be 0 or 1."
        print(f"[ERROR] {err_msg}")
        return False, err_msg
        
    cmd = ["adb"]
    if device_id:
        cmd.extend(["-s", device_id])
        
    cmd.extend([
        "shell", "cmd", "phone", "get-allowed-network-types-for-users",
        "-s", str(sim_slot)
    ])
    
    print(f"[*] Querying allowed network types for SIM {sim_slot + 1}...")
    print(f"[*] Command: {' '.join(cmd)}")
    
    success, stdout, stderr = run_adb_command(cmd)
    if success:
        clean_out = stdout.strip()
        matched_name = parse_network_tech_string(clean_out)
        print(f"[+] Query succeeded. SIM {sim_slot + 1} Allowed types: {clean_out}")
        print(f"    -> Configuration: {matched_name}")
        return True, clean_out
    else:
        err_msg = stderr if stderr else stdout
        print(f"[ERROR] Query failed for SIM {sim_slot + 1}. Details: {err_msg}")
        return False, err_msg


if __name__ == "__main__":
    print("==================================================")
    print("Android Allowed Network Type Manager via ADB")
    print("==================================================")
    
    # 1. Verify ADB connection and find connected devices
    print("[*] Checking connected ADB devices...")
    ok, out, err = run_adb_command(["adb", "devices"])
    if not ok:
        print(f"[ERROR] ADB connection check failed: {err}")
        sys.exit(1)
        
    print(f"[+] Connected devices list:\n{out}\n")
    
    # Get all active device serial numbers
    devices = [line.split()[0] for line in out.splitlines()[1:] if line.strip() and "device" in line]
    if not devices:
        print("[WARNING] No Android devices found via ADB.")
        print("[*] Please connect an Android device and ensure USB debugging is enabled.")
        sys.exit(1)
        
    target_device = devices[0]
    print(f"[+] Target device selected: {target_device}")
    
    # 2. Get status before setting
    print("\n--- Current Status ---")
    get_allowed_network_type(0, device_id=target_device)
    get_allowed_network_type(1, device_id=target_device)
    
    # 3. Demonstration of changing the network type and checking again
    print("\n--- Example: Set SIM 1 to NR | LTE (Disable 2G/3G) ---")
    if set_allowed_network_type(0, NetworkMask.NR_LTE, device_id=target_device):
        get_allowed_network_type(0, device_id=target_device)
        
    print("\n--- Example: Restore SIM 1 to Default (All networks auto) ---")
    if set_allowed_network_type(0, NetworkMask.DEFAULT, device_id=target_device):
        get_allowed_network_type(0, device_id=target_device)
