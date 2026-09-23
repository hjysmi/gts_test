import sys
import argparse
import warnings
import json

# Ignore QUTS internal SyntaxWarnings caused by backslashes in docstrings
warnings.filterwarnings("ignore", category=SyntaxWarning)

# 1. 将 QUTS 支持 Python 脚本的路径加入 Python Path
sys.path.append(r'C:\Program Files (x86)\Qualcomm\QUTS\Support\python')

try:
    import QutsClient
    import DeviceConfigService.DeviceConfigService
    import DeviceConfigService.constants
except ImportError:
    print("导入失败: 请确保 QUTS 已安装且 Python 路径配置正确。")
    sys.exit(1)

# TX 参数到 NV 73841 写入值的映射表
TX_NV73841_MAP = {
    "tx0": 0,   # 测 TX0 (0x00)
    "tx1": 17,  # 测 TX1 (0x11)
    "tx2": 34,  # 测 TX2 (0x22)
    "tx3": 51   # 测 TX3 (0x33)
}

# 默认恒定的 NV 73971 全局配置 (ASDiv Bands Master)
NV_73971_JSON = json.dumps({
    "Version": 1,
    "Master_NV_1X": "DO NOT CARE",
    "Master_NV_HDR": "DO NOT CARE",
    "Master_NV_GSM": "ENABLE",
    "Master_NV_WCDMA": "ENABLE",
    "Master_NV_TDSCDMA": "DO NOT CARE",
    "Master_NV_LTE": "ENABLE",
    "Master_NV_WLAN": "DO NOT CARE",
    "Master_NV_NR5G": "ENABLE",
    "Reserved": [0, 0, 0, 0, 0]
})

def modify_nv_for_device(target_adb_serial, nv_id="70239", nv_value="3"):
    print(f"正在初始化 QUTS 客户端，寻找目标设备: {target_adb_serial} ...")
    quts_client = QutsClient.QutsClient("Targeted_NV_Modifier")
    dev_manager = quts_client.getDeviceManager()
    
    # 2. 获取所有已连接的设备列表的详细信息
    device_list = dev_manager.getDeviceList()
    
    if not device_list:
        print("未检测到任何与 QUTS 连接的设备！")
        return False
        
    target_handle = None
    
    print("\n[当前已连接的设备列表]")
    for dev in device_list:
        print(f" - ADB Serial: {dev.adbSerialNumber} | Device Handle: {dev.deviceHandle}")
        
        # 3. 匹配指定的 ADB 设备号 (同时兼容 USB设备的序列号 和 IP:PORT)
        if dev.adbSerialNumber == target_adb_serial or dev.serialNumber == target_adb_serial:
            target_handle = dev.deviceHandle
            
    if target_handle is None:
        print(f"\n❌ 错误: 未找到 ADB 序列号为 '{target_adb_serial}' 的设备。")
        return False
        
    print(f"\n✅ 已锁定目标设备 [{target_adb_serial}]，设备分配句柄: {target_handle}")
    
    # 4. 确认该设备是否支持 DeviceConfig 服务
    service_name = DeviceConfigService.constants.DEVICE_CONFIG_SERVICE_NAME
    supported_handles = dev_manager.getDevicesForService(service_name)
    
    if target_handle not in supported_handles:
        print(f"❌ 错误: 目标设备 [{target_adb_serial}] 不支持配置服务 (DeviceConfigService)，无法修改 NV！")
        return False

    # 5. [核心步骤] 为指定的 deviceHandle 创建配置服务
    dev_config = DeviceConfigService.DeviceConfigService.Client(
        quts_client.createService(service_name, target_handle)
    )
    
    if dev_config.initializeService() != 0:
        print("❌ 初始化设备配置服务失败:", dev_config.getLastError())
        return False
        
    # 6. 执行 NV 修改
    sub_id = -1 # -1 代表默认卡槽 NO_SUBSCRIPTION_ID
    print(f"\n正在将设备 [{target_adb_serial}] 的 NV 项 {nv_id} 修改为 {nv_value} ...")
    error_code = dev_config.nvSetItem(nv_id, str(nv_value), sub_id)
    
    success = False
    if error_code == 0:
        print("🎉 NV 修改成功！")
        success = True
    else:
        print("❌ NV 修改失败，QUTS 底层报错信息:", dev_config.getLastError())
        
    # 7. 清理并注销服务
    dev_config.destroyService()
    return success

def query_nv_for_device(target_adb_serial, nv_id="73971"):
    print(f"\n正在初始化 QUTS 客户端，查询目标设备 [{target_adb_serial}] 的 NV {nv_id} ...")
    quts_client = QutsClient.QutsClient("Targeted_NV_Querier")
    dev_manager = quts_client.getDeviceManager()
    
    device_list = dev_manager.getDeviceList()
    if not device_list:
        print("未检测到任何与 QUTS 连接的设备！")
        return None
        
    target_handle = None
    for dev in device_list:
        if dev.adbSerialNumber == target_adb_serial or dev.serialNumber == target_adb_serial:
            target_handle = dev.deviceHandle
            
    if target_handle is None:
        print(f"❌ 错误: 未找到 ADB 序列号为 '{target_adb_serial}' 的设备。")
        return None
        
    service_name = DeviceConfigService.constants.DEVICE_CONFIG_SERVICE_NAME
    if target_handle not in dev_manager.getDevicesForService(service_name):
        print(f"❌ 错误: 目标设备 [{target_adb_serial}] 不支持配置服务 (DeviceConfigService)！")
        return None

    dev_config = DeviceConfigService.DeviceConfigService.Client(
        quts_client.createService(service_name, target_handle)
    )
    
    if dev_config.initializeService() != 0:
        print("❌ 初始化设备配置服务失败:", dev_config.getLastError())
        return None
        
    sub_id = -1
    index = 0
    query_result = None
    
    try:
        import DeviceConfigService.ttypes as ttypes
        # 请求返回 JSON 格式文本
        return_config = ttypes.NvReturns(flags=ttypes.NvReturnFlags.JSON_TEXT)
        print(f"正在通过 QUTS 接口 nvReadItem 读取 NV {nv_id} ...")
        result = dev_config.nvReadItem(nv_id, sub_id, index, return_config)
        
        if result.errorCode != 0:
            print(f"❌ 读取 NV 失败，QUTS 错误码: {result.errorCode}")
        else:
            # 1. 优先尝试解析并美观打印 JSON 返回
            if result.parsedJson:
                try:
                    parsed_json = json.loads(result.parsedJson)
                    print(f"✅ 查询成功！NV {nv_id} 结构如下:")
                    print(json.dumps(parsed_json, indent=4, ensure_ascii=False))
                    query_result = parsed_json
                except Exception:
                    print(f"✅ 查询成功！NV {nv_id} 原始 JSON 字符串:\n{result.parsedJson}")
                    query_result = result.parsedJson
            # 2. 如果无 JSON 则退而求其次打印解析文本
            elif result.parsedText:
                print(f"✅ 查询成功！NV {nv_id} 解析值为:\n{result.parsedText}")
                query_result = result.parsedText
            # 3. 如果只有原始二进制负载
            elif result.payload:
                print(f"✅ 查询成功！NV {nv_id} 原始 Payload (字节数: {len(result.payload)}): {result.payload.hex()}")
                query_result = result.payload.hex()
            else:
                print(f"✅ 查询成功，但 NV {nv_id} 返回的内容为空。")
                
    except Exception as e:
        print(f"❌ 读取 NV 过程发生异常: {e}")

    dev_config.destroyService()
    return query_result

def set_antenna_tx(target_adb_serial, tx="tx0"):
    """
    根据 tx 参数 ('tx0', 'tx1', 'tx2', 'tx3') 映射并配置 NV 73841:
      - tx0 -> 0
      - tx1 -> 17
      - tx2 -> 34
      - tx3 -> 51
    """
    tx_key = tx.lower()
    if tx_key not in TX_NV73841_MAP:
        print(f"❌ 错误: 无效的 tx 参数 '{tx}'。可选值为: {list(TX_NV73841_MAP.keys())}")
        return False
        
    nv_val = TX_NV73841_MAP[tx_key]
    print(f"\n[*] 映射 TX 选择: '{tx.upper()}' -> 目标 NV 73841 写入值: {nv_val}")
    modify_ok = modify_nv_for_device(target_adb_serial, nv_id="73841", nv_value=str(nv_val))
    query_nv_for_device(target_adb_serial, nv_id="73841")
    return modify_ok

def main():
    parser = argparse.ArgumentParser(description="Qualcomm NV Modification Tool")
    parser.add_argument("device", nargs="?", default="NAVR120201", 
                        help="Target ADB serial number (positional, default: NAVR120201)")
    parser.add_argument("--serial", dest="serial_opt", 
                        help="Target ADB serial number (optional flag)")
    parser.add_argument("--tx", choices=["tx0", "tx1", "tx2", "tx3", "TX0", "TX1", "TX2", "TX3"], 
                        default="tx0", 
                        help="TX antenna selection: tx0 (0), tx1 (17), tx2 (34), tx3 (51). Default: tx0")
                        
    args = parser.parse_args()
    target_device = args.serial_opt if args.serial_opt else args.device
    selected_tx = args.tx.lower()
    
    print("="*60)
    print("QUALCOMM NV CONFIGURATION (NV 73841 & NV 73971)")
    print(f"  Target Device: {target_device}")
    print(f"  Target TX    : {selected_tx.upper()} (NV 73841 = {TX_NV73841_MAP[selected_tx]})")
    print("="*60)
    
    # 步骤 1: 写入复杂的 JSON NV 73971
    print("\n===== 步骤 1: 写入并查询复杂的 JSON NV 73971 =====")
    modify_nv_for_device(target_device, nv_id="73971", nv_value=NV_73971_JSON)
    query_nv_for_device(target_device, nv_id="73971")
    
    # 步骤 2: 根据 tx 参数设置单值 NV 73841
    print(f"\n===== 步骤 2: 根据 tx={selected_tx.upper()} 设置并查询单值 NV 73841 =====")
    set_antenna_tx(target_device, tx=selected_tx)

if __name__ == "__main__":
    main()
