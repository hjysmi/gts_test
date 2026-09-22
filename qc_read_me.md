# Qualcomm Antenna Force & RX Test End-to-End Orchestration Tool (qc_main.py)

本工具专为 **Qualcomm (高通)** 平台手机在开发、射频调试（RF Test）或量产测试阶段设计，旨在通过 **Qualcomm QUTS (DeviceConfig & QXDM Service)** 与 **ADB 命令行**，全自动执行 XQCN 备份文件恢复、NV 项覆盖写入与校验、网络制式屏蔽变更、物理天线强制发射通路（ASDiv）设定以及分集接收（RX）路径选择的连贯测试编排。

---

## 🚀 核心工作流 (5 大测试步骤)

当运行 `qc_main.py` 时，脚本会安全且严格地按照以下顺序执行 5 步编排：

```
[开始] ──> 1. 覆盖写入并读取校验 NV 73841 和 NV 73971 (qc_nv.py)
         └──> 2. 基于 ADB 切换 Android 允许的网络类型 (LTE Only / NR Only) 
         └──> 3. 强迫 TX 天线切换 / 写入 ASDiv (qc_efs_tx.py) 
         └──> 4. 强迫 LTE RX 路径切换 (qc_lte_rx.py, 若在第2步选择5G NR则自动静默跳过此步) 
         └──> 5. 还原 QCN/XQCN 备份文件 (qc_restore_xqcn.py, 移动至最后一步) ──> [结束]
```

---

## 📋 参数解读 (Parameter Interpretation)

无论是通过**命令行（CLI）** 还是在代码中传递 **`params` 字典**，所有配置参数都需遵循以下严格的规则及校验。

| 参数名 (CLI) | 字典 Key (Dict) | 类型 (Type) | 必填 | 取值范围 / 选项 | 物理含义与校验规则 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `--serial` | `"serial"` | `str` | **是** | *非空字符串* | **目标 ADB 序列号**。<br>• 匹配手机的 adb 序列号（如 `N2FM220209`）以供 QUTS 与 ADB 精准下发控制。 |
| `--qcn-file` | `"qcn_file"` | `str` | **是** | *合法的文件路径* | **QCN/XQCN 备份文件的完整绝对路径**。<br>• 强校验：如果文件不存在或不是合法绝对路径，将立刻安全拦截。 |
| `--rat` | `"rat"` | `str` | **是** | `LTE`, `LTE_ONLY`, `NR`, `NR_ONLY` | **测试目标通信制式**。<br>• `LTE` / `LTE_ONLY` 代表 4G 模式。<br>• `NR` / `NR_ONLY` 代表 5G 模式。 |
| `--ant-value` | `"ant_value"` | `str` | **是** | `0`, `00`, `1`, `11`, `2`, `22`, `3`, `33`, `default`, `FF` | **ASDiv 天线强迫值**（物理发射天线设定）。<br>• `00` / `0`: 强迫 Config0 (ANT1)<br>• `11` / `1`: 强迫 Config1 (ANT2)<br>• `22` / `2`: 强迫 Config2 (ANT3)<br>• `33` / `3`: 强迫 Config3 (ANT4)<br>• `FF` / `default`: 恢复默认自动切换。 |
| `--rx-mode` | `"rx_mode"` | `str` | *条件* | `combine`, `rx0`, `rx1`, `rx2`, `rx3` | **LTE RX 路径强迫配置模式**。<br>• **LTE** 下：**必填**参数。<br>• **NR** 下：**自动忽略并跳过**该步骤。 |
| `--network-mask`| `"network_mask"`| `str` | **是** | `LTE_ONLY`, `NR_ONLY`, `NR_LTE`, `DEFAULT` | **测试目标网络掩码**。<br>• **必填**参数。指定切换后的网络屏蔽状态。<br>• 校验规则：必须匹配 `android_network_manager.py` 底层定义的网络类型。 |
| `--sim-slot` | `"sim_slot"` | `int` | *否* | `0`, `1` | **SIM 卡槽**（默认为 `0`）。<br>• `0` 代表卡 1，`1` 代表卡 2。 |

---

## ⚠️ 参数强校验规则 (Validation Rules)

本脚本在执行首步操作前，会通过 `validate_params()` 启动强类型和业务规则校检，以下任意不匹配项均会**立刻拦截并安全报错**：

1. **QCN 文件全路径存在校检**:
   * 如果传入的 `--qcn-file` 不是绝对路径，程序会自动将其解析为绝对路径。
   * 如果该文件在 PC 磁盘上不存在，程序会抛出 `ValueError` 并强行中断。
2. **接收天线状态 (LTE Rx Mode) 隔离规则**:
   * **LTE / LTE_ONLY** 模式下：程序硬性限制**必须传入** `rx_mode` 参数。若遗漏将抛出错误。
   * **NR / NR_ONLY** 模式下：程序将**自动在步骤 5 中输出 log 并静默跳过**对 `qc_lte_rx.py` 的调用（即使在命令行中传入了 `rx_mode` 也会安全忽略，保障 5G 下不执行 LTE RX 的无用强迫）。
3. **接口取值域验证**:
   * 严格核对 `ant_value` 与 `rx_mode` 属于高通物理对应合法的指令集中。

---

## 💻 调用示例 (Execution Examples)

### 1. 命令行调用 (CLI Options)

根据具体测试制式选择以下合理的调用指令：

#### A. 4G LTE 场景：NV 覆盖、4G网络锁定、TX 强迫、RX0 强迫、XQCN 恢复
```bash
python qc_main.py --serial NAVR120201 --qcn-file D:\share_179\0519\bank_prod\Avenger_0914.xqcn --rat LTE --ant-value 11 --rx-mode rx0 --sim-slot 0 --network-mask LTE_ONLY
```

#### B. 5G NR 场景：NV 覆盖、5G网络锁定、TX 强迫、XQCN 恢复 (自动跳过 LTE RX 配置)
```bash
python qc_main.py --serial NAVR120201 --qcn-file D:\share_179\0519\bank_prod\Avenger_0914.xqcn --rat NR --ant-value 00 --sim-slot 0 --network-mask NR_ONLY
```

---

### 2. Python 模块字典传参调用 (Module Integration)

可以在其他 Python 测试框架或自动化套件中直接集成该工作流：

```python
import sys
from qc_main import validate_params, run_qc_orchestration_flow

# 1. 准备您的测试字典类参数
qc_test_config = {
    "serial": "NAVR120201",
    "qcn_file": r"D:\xqcn\Avenger_0914.xqcn",
    "rat": "LTE",
    "ant_value": "11",
    "rx_mode": "rx0",
    "sim_slot": 0,
}

# 2. 放入 try-catch 块中执行
try:
    print("[*] 正在对输入字典执行严格高通射频一致性校验...")
    validate_params(qc_test_config)
    
    print("[*] 校验通过！正在拉起高通 5 步自动化测试编排流程...")
    success = run_qc_orchestration_flow(qc_test_config)
    
    if success:
        print("[+] 恭喜，高通平台测试流程连贯完成！")
    else:
        print("[-] 警告：编排流程执行中存在步骤告警。")
        
except ValueError as e:
    print(f"[PARAM ERROR] 阻断型参数配置冲突: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FATAL ERROR] 运行发生非预期故障: {e}")
    sys.exit(1)
```

---

## 📁 关联子模块说明

* **`qc_main.py`**：高通核心编排调度器，负责参数清洗、整包强校检和跨脚本连贯控制。
* **`qc_restore_xqcn.py`**：调用 QUTS DeviceConfigService 专属还原 `.xqcn` / `.qcn` 数据并监控进度。
* **`qc_nv.py`**：控制 NV 73841 (覆盖模式开关) 与 NV 73971 (ASDiv bands master) 的高精度读写与格式化。
* **`qc_efs_tx.py`**：调用 QUTS QXDM 诊断服务向 EFS 物理节点快速打入天线 Config 强迫参数并离线再在线激活。
* **`qc_lte_rx.py`**：专门在 4G 下负责读取、清空 `/nv/item_files/modem/lte/ML1` 目录，上传对应的 `rx_select` 分集接收配置。
* **`android_network_manager.py`**：通用底层 ADB 网络屏蔽及切换控制器。
