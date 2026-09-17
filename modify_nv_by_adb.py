import sys
import argparse

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

if __name__ == "__main__":
    # 支持在命令行直接传入 ADB 设备号，例如: python modify_nv_by_adb.py 10.125.176.206:5555
    # 如果没有传入参数，则使用下方配置的默认值
    if len(sys.argv) > 1:
        target_device = sys.argv[1]
    else:
        # 修改这里的字符串来选择默认调试的设备
        target_device = "NAVR120201" 
        # target_device = "10.125.176.206:5555"
        
    modify_nv_for_device(target_device, nv_id="70239", nv_value="3")