import sys
import os

# 1. 将 QUTS 支持 Python 脚本的路径加入 Python Path
sys.path.append(r'C:\Program Files (x86)\Qualcomm\QUTS\Support\python')

# 2. 【核心修复】猴子补丁 (Monkey-patch) 解决 Thrift string 类型在 Python 3 中强行编码 bytes 的类型 Bug
try:
    import thrift.compat
    thrift.compat.str_to_binary = lambda s: s if isinstance(s, bytes) else bytes(s, 'utf8')
    print("ℹ️ 成功加载 Thrift 类型兼容性补丁。")
except Exception as e:
    print(f"⚠️ 警告: 尝试注入 Thrift 补丁时出现异常: {e}")

try:
    import QutsClient
    import DeviceConfigService.DeviceConfigService
    import DeviceConfigService.constants
except ImportError:
    print("导入失败: 请确保 QUTS 已安装且 Python 路径配置正确。")
    sys.exit(1)

def restore_xqcn_for_device(target_adb_serial, xqcn_path="Avenger_0914.xqcn"):
    # 3. 验证 QCN/XQCN 文件是否存在并读取其内容
    if not os.path.exists(xqcn_path):
        print(f"❌ 错误: 找不到指定的 QCN/XQCN 备份文件: {xqcn_path}")
        return

    print(f"正在加载备份文件: {xqcn_path} ...")
    try:
        with open(xqcn_path, 'rb') as f:
            xqcn_data = f.read()
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return

    print(f"正在初始化 QUTS 客户端，寻找目标设备: {target_adb_serial} ...")
    quts_client = QutsClient.QutsClient("Targeted_QCN_Importer")
    dev_manager = quts_client.getDeviceManager()
    
    # 4. 获取所有已连接设备，并比对匹配相应的 ADB 序列号以获取设备句柄
    device_list = dev_manager.getDeviceList()
    if not device_list:
        print("未检测到任何与 QUTS 连接的设备！")
        return
        
    target_handle = None
    print("\n[当前已连接的设备列表]")
    for dev in device_list:
        print(f" - ADB Serial: {dev.adbSerialNumber} | Device Handle: {dev.deviceHandle}")
        if dev.adbSerialNumber == target_adb_serial or dev.serialNumber == target_adb_serial:
            target_handle = dev.deviceHandle
            
    if target_handle is None:
        print(f"\n❌ 错误: 未找到 ADB 序列号为 '{target_adb_serial}' 的设备。")
        return
        
    print(f"\n✅ 已锁定目标设备 [{target_adb_serial}]，设备分配句柄: {target_handle}")
    
    # 5. 确认设备是否支持配置服务
    service_name = DeviceConfigService.constants.DEVICE_CONFIG_SERVICE_NAME
    supported_handles = dev_manager.getDevicesForService(service_name)
    if target_handle not in supported_handles:
        print(f"❌ 错误: 目标设备 [{target_adb_serial}] 不支持配置服务 (DeviceConfigService)，无法导入 QCN！")
        return

    # 6. 为指定 deviceHandle 专属创建配置服务并初始化
    dev_config = DeviceConfigService.DeviceConfigService.Client(
        quts_client.createService(service_name, target_handle)
    )
    
    if dev_config.initializeService() != 0:
        print("❌ 初始化设备配置服务失败:", dev_config.getLastError())
        return
        
    # 7. 配置 QCN 还原参数 (Allow ESN Mismatch & Reset Device 默认开启)
    spc_code = "000000"          # 默认 6 位 SPC 安全解锁码
    allow_esn_mismatch = True    # 默认开启 Allow ESN Mismatch
    reset_upon_completion = True # 默认开启 导入后重启手机
    reset_timeout_ms = 15000     # 默认等待重启响应的超时时间 (15秒)
    filter_xml_content = ""      # 默认还原全部 NV (空字符)
    
    print(f"\n正在向设备 [{target_adb_serial}] 导入 XQCN 备份...")
    print(f" - 允许 ESN/IMEI 错配: {allow_esn_mismatch}")
    print(f" - 导入完成后自动重启: {reset_upon_completion}")
    
    # 8. 调用 QUTS 接口执行导入
    error_code = dev_config.restoreFromXqcn(
        xqcn_data,
        spc_code,
        allow_esn_mismatch,
        reset_upon_completion,
        reset_timeout_ms,
        filter_xml_content
    )
    
    if error_code == 0:
        print("\n🎉 QCN/XQCN 导入指令成功下发并写入完毕！设备已自动安排重启。")
        success = True
    else:
        print(f"\n❌ 导入失败，QUTS 报错代码: {error_code}")
        print("❌ 报错信息详情:", dev_config.getLastError())
        success = False
        
    # 9. 清理并销毁服务
    dev_config.destroyService()
    return success

if __name__ == "__main__":
    # 参数 1: 目标 ADB 序列号 (例如 "NAVR120201" 或 "10.125.176.206:5555")
    # 参数 2: XQCN 文件路径 (可选，默认使用当前目录下的 "Avenger_0914.xqcn")
    
    if len(sys.argv) < 2:
        print("💡 使用说明:")
        print("  python qc_restore_xqcn.py <ADB_SERIAL> [xqcn_file_path]")
        print("\n  示例:")
        print("  python qc_restore_xqcn.py NAVR120201")
        print("  python qc_restore_xqcn.py 10.125.176.206:5555 D:\\my_backup.xqcn\n")
        sys.exit(1)
        
    adb_serial = sys.argv[1]
    
    # 获取 QCN/XQCN 文件路径变量，默认是当前路径下的 "Avenger_0914.xqcn"
    qcn_file = "Avenger_0914.xqcn"
    if len(sys.argv) > 2:
        qcn_file = sys.argv[2]
        
    restore_xqcn_for_device(adb_serial, xqcn_path=qcn_file)