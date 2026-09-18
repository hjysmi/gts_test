import sys
import argparse
import warnings
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

def modify_nv_for_device(target_adb_serial, nv_id="70239", nv_value="3"):
    print(f"正在初始化 QUTS 客户端，寻找目标设备: {target_adb_serial} ...")
    quts_client = QutsClient.QutsClient("Targeted_NV_Modifier")
    dev_manager = quts_client.getDeviceManager()
    
    # 2. 获取所有已连接的设备列表的详细信息
    device_list = dev_manager.getDeviceList()
    
    if not device_list:
        print("未检测到任何与 QUTS 连接的设备！")
        return
        
    target_handle = None
    
    print("\n[当前已连接的设备列表]")
    for dev in device_list:
        print(f" - ADB Serial: {dev.adbSerialNumber} | Device Handle: {dev.deviceHandle}")
        
        # 3. 匹配指定的 ADB 设备号 (同时兼容 USB设备的序列号 和 IP:PORT)
        if dev.adbSerialNumber == target_adb_serial or dev.serialNumber == target_adb_serial:
            target_handle = dev.deviceHandle
            
    if target_handle is None:
        print(f"\n❌ 错误: 未找到 ADB 序列号为 '{target_adb_serial}' 的设备。")
        return
        
    print(f"\n✅ 已锁定目标设备 [{target_adb_serial}]，设备分配句柄: {target_handle}")
    
    # 4. 确认该设备是否支持 DeviceConfig 服务
    service_name = DeviceConfigService.constants.DEVICE_CONFIG_SERVICE_NAME
    supported_handles = dev_manager.getDevicesForService(service_name)
    
    if target_handle not in supported_handles:
        print(f"❌ 错误: 目标设备 [{target_adb_serial}] 不支持配置服务 (DeviceConfigService)，无法修改 NV！")
        return

    # 5. [核心步骤] 为指定的 deviceHandle 创建配置服务
    dev_config = DeviceConfigService.DeviceConfigService.Client(
        quts_client.createService(service_name, target_handle)
    )
    
    if dev_config.initializeService() != 0:
        print("❌ 初始化设备配置服务失败:", dev_config.getLastError())
        return
        
    # 6. 执行 NV 修改
    sub_id = -1 # -1 代表默认卡槽 NO_SUBSCRIPTION_ID
    print(f"\n正在将设备 [{target_adb_serial}] 的 NV 项 {nv_id} 修改为 {nv_value} ...")
    error_code = dev_config.nvSetItem(nv_id, str(nv_value), sub_id)
    
    if error_code == 0:
        print("🎉 NV 修改成功！")
    else:
        print("❌ NV 修改失败，QUTS 底层报错信息:", dev_config.getLastError())
        
    # 7. 清理并注销服务
    dev_config.destroyService()

def query_nv_for_device(target_adb_serial, nv_id="73971"):
    print(f"\n正在初始化 QUTS 客户端，查询目标设备 [{target_adb_serial}] 的 NV {nv_id} ...")
    quts_client = QutsClient.QutsClient("Targeted_NV_Querier")
    dev_manager = quts_client.getDeviceManager()
    
    device_list = dev_manager.getDeviceList()
    if not device_list:
        print("未检测到任何与 QUTS 连接的设备！")
        return
        
    target_handle = None
    for dev in device_list:
        if dev.adbSerialNumber == target_adb_serial or dev.serialNumber == target_adb_serial:
            target_handle = dev.deviceHandle
            
    if target_handle is None:
        print(f"❌ 错误: 未找到 ADB 序列号为 '{target_adb_serial}' 的设备。")
        return
        
    service_name = DeviceConfigService.constants.DEVICE_CONFIG_SERVICE_NAME
    if target_handle not in dev_manager.getDevicesForService(service_name):
        print(f"❌ 错误: 目标设备 [{target_adb_serial}] 不支持配置服务 (DeviceConfigService)！")
        return

    dev_config = DeviceConfigService.DeviceConfigService.Client(
        quts_client.createService(service_name, target_handle)
    )
    
    if dev_config.initializeService() != 0:
        print("❌ 初始化设备配置服务失败:", dev_config.getLastError())
        return
        
    sub_id = -1
    index = 0
    
    try:
        import DeviceConfigService.ttypes as ttypes
        # 请求返回 JSON 格式文本
        return_config = ttypes.NvReturns(flags=ttypes.NvReturnFlags.JSON_TEXT)
        print(f"正在通过 QUTS 接口 nvReadItem 读取 NV {nv_id} ...")
        result = dev_config.nvReadItem(nv_id, sub_id, index, return_config)
        
        if result.errorCode != 0:
            print(f"❌ 读取 NV 失败，QUTS 错误码: {result.errorCode}")
        else:
            import json
            # 1. 优先尝试解析并美观打印 JSON 返回 (无论是多 Item 还是单 Item)
            if result.parsedJson:
                try:
                    parsed_json = json.loads(result.parsedJson)
                    print(f"✅ 查询成功！NV {nv_id} 结构如下:")
                    print(json.dumps(parsed_json, indent=4, ensure_ascii=False))
                except Exception:
                    print(f"✅ 查询成功！NV {nv_id} 原始 JSON 字符串:\n{result.parsedJson}")
            # 2. 如果无 JSON 则退而求其次打印解析文本
            elif result.parsedText:
                print(f"✅ 查询成功！NV {nv_id} 解析值为:\n{result.parsedText}")
            # 3. 如果只有原始二进制负载
            elif result.payload:
                print(f"✅ 查询成功！NV {nv_id} 原始 Payload (字节数: {len(result.payload)}): {result.payload.hex()}")
            else:
                print(f"✅ 查询成功，但 NV {nv_id} 返回的内容为空。")
                
    except Exception as e:
        print(f"❌ 读取 NV 过程发生异常: {e}")

    dev_config.destroyService()

if __name__ == "__main__":
    # 需求是 
    # 1. 修改NV73971为nv_73971_json
    # 2. NV73841为0
    #
    # 支持在命令行直接传入 ADB 设备号，例如: python modify_nv_by_adb.py 10.125.176.206:5555
    # 如果没有传入参数，则使用下方配置的默认值
    if len(sys.argv) > 1:
        target_device = sys.argv[1]
    else:
        # 修改这里的字符串来选择默认调试的设备
        target_device = "NAVR120201" 
        # target_device = "10.125.176.206:5555"
        
    import json
    
    # 步骤 1: 写入前先查询目前的 NV 73971 状态
    print("===== 阶段 0: 写入前查询 NV 73971 =====")
    query_nv_for_device(target_device, nv_id="73971")
    
    # 步骤 2: 写入复杂的 JSON NV (如 73971)
    # 根据 QUTS 底层 Schema 结构，多 Item NV（如 Union 联合体）在写入时需要将
    # 判别器 "Version" 与对应版本（如 V1）的子字段合并在 Top Level (扁平结构) 传入
    nv_73971_json = json.dumps({
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
    print("\n===== 阶段 1: 写入复杂的 JSON NV 73971 =====")
    modify_nv_for_device(target_device, nv_id="73971", nv_value=nv_73971_json)
    
    # 步骤 3: 写入后再查询确认
    print("\n===== 阶段 2: 写入后查询 NV 73971 确认 =====")
    query_nv_for_device(target_device, nv_id="73971")
    
    # 步骤 4: 查询单值 NV (用于测试向下兼容性)
    print("\n===== 阶段 3: 查询单值 NV 73841 =====")
    query_nv_for_device(target_device, nv_id="73841")