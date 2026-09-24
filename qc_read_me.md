# Qualcomm Antenna Force & RX Test End-to-End Orchestration Tool (qc_main.py)

本工具专为 **Qualcomm (高通)** 平台手机在开发、射频调试（RF Test）或量产测试阶段设计，旨在通过 **Qualcomm QUTS (DeviceConfig & QXDM Service)** 与 **ADB 命令行**，全自动执行 USB 端口模式检查与自动配置、NV 项覆盖写入与校验（强制 TX 通路及 ASDiv Master 开关）、网络制式屏蔽变更、分集接收（RX）路径选择以及 XQCN 备份文件恢复的连贯测试编排。

---

## 🚀 核心工作流 (4 大测试步骤)

当运行 `qc_main.py` 时，脚本会安全且严格地按照以下顺序执行编排：

```
[开始] ──> 0. 检查 sys.usb.config (若非 diag 则自动进入 bootloader 切换 bootmode qcom 并重启)
         └──> 1. 覆盖写入并读取校验 NV 73841 (TX通路) 和 NV 73971 (qc_nv.py)
         └──> 2. 基于 ADB 切换 Android 允许的网络类型 (LTE Only / NR Only) 
         └──> 3. 强迫 LTE RX 路径切换 (qc_lte_rx.py, 若在第2步选择5G NR则自动静默跳过此步) 
         └──> 4. 还原 QCN/XQCN 备份文件 (qc_restore_xqcn.py) ──> [结束]
```

---

## 📋 参数解读 (Parameter Interpretation)

无论是通过**命令行（CLI）** 还是在代码中传递 **`params` 字典**，所有配置参数都需遵循以下严格的规则及校验。

| 参数名 (CLI) | 字典 Key (Dict) | 类型 (Type) | 必填 | 取值范围 / 选项 | 物理含义与校验规则 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `--serial` | `"serial"` | `str` | **是** | *非空字符串* | **目标 ADB 序列号**。<br>• 匹配手机的 adb 序列号（如 `N2FM220209`）以供 QUTS 与 ADB 精准下发控制。 |
| `--qcn-file` | `"qcn_file"` | `str` | **是** | *合法的文件路径* | **QCN/XQCN 备份文件的完整绝对路径**。<br>• 强校验：如果文件不存在或不是合法绝对路径，将立刻安全拦截。 |
| `--rat` | `"rat"` | `str` | **是** | `LTE` (或 `LTE_ONLY`)<br>`NR_SA` (或 `NR`, `NR_ONLY`)<br>`NR_NSA` (或 `NR_LTE`) | **测试目标通信制式（已合并原 --network-mask，自动联动底层网络掩码）**。<br>• `LTE` / `LTE_ONLY`: 4G LTE 模式，底层自动配置掩码 `LTE_ONLY`<br>• `NR_SA` / `NR_ONLY` / `NR`: 5G SA 独立组网，底层自动配置掩码 `NR_ONLY`<br>• `NR_NSA` / `NR_LTE`: 5G NSA 非独立组网，底层自动配置掩码 `NR_LTE`（保留 4G 锚点避免脱网） |
| `--tx` | `"tx"` | `str` | **是** | `tx0`, `tx1`, `tx2`, `tx3`, `0`, `1`, `2`, `3` | **发射天线测试目标 (NV 73841)**。<br>• `tx0` / `0`: NV 73841 = `0` (0x00，测 TX0)<br>• `tx1` / `1`: NV 73841 = `17` (0x11，测 TX1)<br>• `tx2` / `2`: NV 73841 = `34` (0x22，测 TX2)<br>• `tx3` / `3`: NV 73841 = `51` (0x33，测 TX3) |
| `--rx-mode` | `"rx_mode"` | `str` | *条件* | `combine_4rx`, `rx0`, `rx1`, `rx2`, `rx3` | **LTE RX 路径强迫配置模式**。<br>• **LTE** 下：**必填**参数。<br>• **NR** (SA/NSA) 下：**自动忽略并跳过**该步骤。 |
| `--sim-slot` | `"sim_slot"` | `int` | *否* | `0`, `1` | **SIM 卡槽**（默认为 `0`）。<br>• `0` 代表卡 1，`1` 代表卡 2。 |
| *(已合并)*<br>`--network-mask` | `"network_mask"` | `str` | *已移除* | `LTE_ONLY`, `NR_ONLY`, `NR_LTE`, `DEFAULT` | **已合并进 `--rat` 自动推导，CLI 命令行参数已移除**。<br>• Python 代码字典调用时无需再传此字段；若历史代码显式传入，系统会自动校验其与 `rat` 是否冲突。 |

---

## ⚠️ 参数强校验与防冲突规则 (Validation Rules)

本脚本在执行首步操作前，会通过 `validate_params()` 启动强类型和业务规则校检，以下任意不匹配项均会**立刻拦截并安全报错**：

1. **制式与网络掩码自适应推导与防冲突**:
   * 无需手动传入网络掩码，系统根据 `--rat` 自动完成推导：
     * `LTE` $\rightarrow$ 自动绑定 `LTE_ONLY`
     * `NR_SA` $\rightarrow$ 自动绑定 `NR_ONLY`
     * `NR_NSA` $\rightarrow$ 自动绑定 `NR_LTE`（保障 4G LTE 锚点驻留）
   * 若外部调用时同时传入了 `network_mask`，将启动**兼容互斥校检**（例如传入 `rat="LTE"` 但 `network_mask="NR_ONLY"` 将直接拦截报错）。
2. **QCN 文件全路径存在校检**:
   * 如果传入的 `--qcn-file` 不是绝对路径，程序会自动将其解析为绝对路径。
   * 如果该文件在 PC 磁盘上不存在，程序会抛出 `ValueError` 并强行中断。
3. **接收天线状态 (LTE Rx Mode) 隔离规则**:
   * **LTE / LTE_ONLY** 模式下：程序硬性限制**必须传入** `rx_mode` 参数。若遗漏将抛出错误。
   * **NR_SA / NR_NSA** 模式下：程序将**自动在步骤 3 中输出 log 并静默跳过**对 `qc_lte_rx.py` 的调用（即使传入了 `rx_mode` 也会提示安全忽略，保障 5G 下不执行 LTE RX 的无用强迫）。
4. **接口取值域验证**:
   * 严格核对 `tx` 与 `rx_mode` 属于高通物理对应合法的指令集中。

---

## 💻 调用示例 (Execution Examples)

### 1. 命令行调用 (CLI Options)

根据具体测试制式选择以下合理的调用指令：

#### A. 4G LTE 场景：NV 覆盖、4G网络锁定、TX 强迫、RX0 强迫、XQCN 恢复
```bash
python qc_main.py --serial NAVR120201 --qcn-file D:\share_179\0519\bank_prod\Avenger_0914.xqcn --rat LTE --tx tx1 --rx-mode rx0 --sim-slot 0
```

#### B. 5G SA 场景：NV 覆盖、5G独占网络锁定、TX 强迫、XQCN 恢复 (自动跳过 LTE RX 配置)
```bash
python qc_main.py --serial NAVR120201 --qcn-file D:\share_179\0519\bank_prod\Avenger_0914.xqcn --rat NR_SA --tx tx0 --sim-slot 0
```

#### C. 5G NSA 场景：NV 覆盖、5G/4G复合网络锁定、TX 强迫、XQCN 恢复 (自动跳过 LTE RX 配置)
```bash
python qc_main.py --serial NAVR120201 --qcn-file D:\share_179\0519\bank_prod\Avenger_0914.xqcn --rat NR_NSA --tx tx0 --sim-slot 0
```

---

### 2. Python 模块字典传参调用 (Module Integration)

可以在其他 Python 测试框架或自动化套件中直接集成该工作流：

```python
import sys
from qc_main import validate_params, run_qc_flow

# 1. 准备您的测试字典类参数 (无需显式指定 network_mask，自动由 rat 推导)
qc_test_config = {
    "serial": "NAVR120201",
    "qcn_file": r"D:\xqcn\Avenger_0914.xqcn",
    "rat": "LTE",
    "tx": "tx1",
    "rx_mode": "rx0",
    "sim_slot": 0,
}

# 2. 放入 try-catch 块中执行
try:
    print("[*] 正在对输入字典执行严格高通射频一致性校验...")
    validate_params(qc_test_config)
    
    print("[*] 校验通过！正在拉起高通自动化测试编排流程...")
    success = run_qc_flow(qc_test_config)
    
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
  * **支持 `--tx` 参数**：
    * `tx0` $\rightarrow$ NV 73841 = `0` (0x00，测 TX0)
    * `tx1` $\rightarrow$ NV 73841 = `17` (0x11，测 TX1)
    * `tx2` $\rightarrow$ NV 73841 = `34` (0x22，测 TX2)
    * `tx3` $\rightarrow$ NV 73841 = `51` (0x33，测 TX3)
* **`qc_lte_rx.py`**：专门在 4G 下负责读取、清空 `/nv/item_files/modem/lte/ML1` 目录，上传对应的 `rx_select` 分集接收配置。
* **`android_network_manager.py`**：通用底层 ADB 网络屏蔽及切换控制器。
* **`qc_efs_tx.py`**：独立辅助脚本，调用 QUTS QXDM 诊断服务向 EFS 物理节点快速写入天线 Config 强迫参数并离线再在线激活。
