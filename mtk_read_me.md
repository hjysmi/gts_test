# MTK Antenna Force & RX Test End-to-End Orchestration Tool (mtk_main.py)

本工具专为 **MediaTek (MTK)** 平台手机在开发、射频调试（RF Test）或量产测试阶段设计，旨在通过 **MACE API (AT 串口)** 与 **ADB 命令行**，全自动执行手机 Logger 状态切换、网络制式更改、发射（TX）及接收（RX）天线强迫设定的连贯测试编排。

---

## 🚀 核心工作流 (7 大测试步骤)

当运行 `mtk_main.py` 时，脚本会安全且严格地按照以下顺序执行 7 步编排：

```
[开始] ──> 1. 停止 MTK Logger ──> 2. 切换 Modem 为 USB 模式 ──> 3. 开启 MTK Logger 
         └──> [建立 MACE 连接] ──> 4. 切换 Android 网络类型 (LTE/NR/Default) 
         └──> 5. 强迫 TX 天线切换 (mtk_tx.py, 无 Logger 控制干扰) 
         └──> 6. 强迫 RX 天线分集切换 (mtk_rx_test.py, 无 Logger 控制干扰) 
         └──> 7. 停止 MTK Logger ──> [结束并保存日志]
```

---

## 📋 参数解读 (Parameter Interpretation)

无论是通过**命令行（CLI）** 还是在代码中传递 **`params` 字典**，所有配置参数都需遵循以下严格的规则及校验。

| 参数名 (CLI) | 字典 Key (Dict) | 类型 (Type) | 必填 | 取值范围 / 选项 | 物理含义与校验规则 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `--rat` | `"rat"` | `str` | **是** | `LTE`, `LTE_TDD`, `NR` | **通信制式**。<br>• `LTE` 代表 LTE FDD 模式。<br>• `LTE_TDD` 代表 LTE TDD 模式。<br>• `NR` 代表 5G Sub6 模式。 |
| `--band` | `"band"` | `int` | **是** | `1 ~ 255` | **测试频段号**。<br>• **LTE 强校检**：如果 RAT 为 `LTE`，频段必须属于 FDD 频段；如果为 `LTE_TDD`，则必须属于 TDD 频段。 |
| `--tx-state` | `"tx_state"` | `int` | **是** | `0 ~ 23`, `255` | **Tx TAS State (发射天线选择状态)**。<br>• 取值代表射频给定的状态切换索引（不等于物理天线编号）。`255` 代表默认（Default）。 |
| `--rx-state` | `"rx_state"` | `int` | *条件* | `0 ~ 23`, `255` | **Rx TAS State (接收天线选择状态)**。<br>• **LTE (FDD)** 下：**绝对不能**传入此参数，底层会自动使用 `tx_state` 填充 Rx 状态。<br>• **LTE_TDD / NR** 下：**必须**传入此参数。 |
| `--ttps-port` | `"ttps_port"` | `int` | **是** | `0`, `1` | **TTPS TX 物理端口**。<br>• 选择射频发射的主通道/副通道端口。 |
| `--sim-slot` | `"sim_slot"` | `int` | **是** | `0`, `1` | **SIM 卡槽**。<br>• `0` 代表卡 1 (SIM 1)，`1` 代表卡 2 (SIM 2)。 |
| `--network-mask`| `"network_mask"`| `str` | **是** | `LTE_ONLY`, `NR_ONLY`, `NR_LTE`, `DEFAULT` | **Android 允许的网络制式掩码**。<br>• `LTE_ONLY`: 仅限 4G<br>• `NR_ONLY`: 仅限 5G<br>• `NR_LTE`: 5G/4G 自动（禁用 2G/3G）<br>• `DEFAULT`: 恢复默认全自动。 |
| `--rx-scenario` | `"rx_scenario"` | `str` | **单/多选** | `Combine_4Rx`, `Combine_2Rx`, `Rx0`, `Rx1`, `Rx2`, `Rx3` | **RX 天线测试测试场景名称**。<br>• `Combine_4Rx`: Combine_4Rx (4Rx 全勾选模式)<br>• `Combine_2Rx`: Combine_2Rx (2Rx 全勾选模式，Rx12+Rx12+Rx12+Rx12)<br>• `Rx0`: Rx0 强迫单通测试<br>• `Rx1`: Rx1 强迫单通测试<br>• `Rx2`: Rx2 强迫双接收分集<br>• `Rx3`: Rx3 强迫分集测试 |

---

## ⚠️ 参数强校验规则 (Validation Rules)

本脚本在执行首步操作前，会通过 `validate_params()` 启动强类型和业务规则校检，以下任意不匹配项均会**立刻拦截并安全报错**：

1. **频段与双工错配拦截 (LTE FDD vs TDD Band)**:
   * **LTE (FDD)** 常用频段集合：`{1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 17, 18, 19, 20, 21, 25, 26, 28, 30, 31, 32, 66, 71}`
   * **LTE TDD** 常用频段集合：`{34, 37, 38, 39, 40, 41, 42, 43, 46, 48}`
   * *例：若 `--rat LTE` (FDD) 但传入 `--band 41`，程序将报错中断。*
2. **接收天线状态 (Rx TAS State) 隔离规则**:
   * **LTE (FDD)** 制式下：程序硬性限制**不得传入** `rx_state`。若强行传入将抛出错误。
   * **LTE TDD** 和 **NR** 制式下：程序硬性限制**必须传入** `rx_state`。若遗漏将抛出错误。
3. **接口取值域验证**:
   * 确保卡槽、端口、天线档位与场景 ID 在出厂硬编码安全取值范围内。

---

## 💻 调用示例 (Execution Examples)

### 1. 命令行调用 (CLI Options)

根据具体测试制式选择以下合理的调用指令：

#### A. LTE FDD 黄金频段 3 强迫发射与分集测试
*发射和接收天线均强制设定为状态 `1`，选择端口 `0`，网络锁定 4G，SIM卡1*
```bash
python mtk_main.py --rat LTE --band 1 --tx-state 0 --ttps-port 1 --sim-slot 0 --network-mask LTE_ONLY --rx-scenario Rx0
```

#### B. LTE TDD 频段 41 强迫发射与分集测试
*时分双工下，强迫发射为状态 `2`，强制接收为状态 `0`（收发分离），网络锁定 4G，SIM卡1*
```bash
python mtk_main.py --rat LTE_TDD --band 41 --tx-state 2 --rx-state 0 --ttps-port 1 --sim-slot 0 --network-mask LTE_ONLY --rx-scenario Rx0
```

#### C. 5G NR 频段 78 强迫发射与分集测试
*强迫发射为状态 `3`，强制接收为状态 `1`，网络自动切换为 5G/4G，SIM卡1*
```bash
python mtk_main.py --rat NR --band 78 --tx-state 3 --rx-state 1 --ttps-port 0 --sim-slot 0 --network-mask NR_LTE --rx-scenario Rx1
```

---

### 2. Python 模块字典传参调用 (Module Integration)

可以在其他 Python 测试脚本、量产套件或 Web 框架中直接集成该工作流。

```python
import sys
from mtk_main import validate_params, run_orchestration_flow

# 1. 准备您的测试字典类参数 (如 5G 场景测试)
test_config = {
    "rat": "NR",
    "band": 78,
    "tx_state": 1,
    "rx_state": 3,
    "ttps_port": 0,
    "sim_slot": 0,
    "network_mask": "NR_LTE",
    "rx_scenario": "Rx0"
}

# 2. 放入 try-catch 块中执行
try:
    print("[*] 正在对输入字典执行严格射频一致性规则校验...")
    validate_params(test_config)
    
    print("[*] 校验通过！正在拉起 MTK 7步自动化编排流程...")
    success = run_orchestration_flow(test_config)
    
    if success:
        print("[+] 恭喜，该频段的强迫天线与射频日志抓取测试全部通过！")
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

## 📁 关联模块说明

* **`mtk_main.py`**：核心流程调度器，负责外部交互、字典校验、全局顺序编排。
* **`mtk_tx.py`**：封装有 `set_antenna_force`，接收由主脚本清洗后的无干扰纯净发射天线配置命令。
* **`mtk_rx_test.py`**：封装有接收分集强迫核心 `run_antenna_rx_test`，支持静默控制 Logger 执行测试。
* **`android_network_manager.py`**：基于 ADB 极速控制 Android 电话子系统底层允许的网络屏蔽掩码。
* **`mtk_atc_md.py`**：用于通过 MACE SDK 进行基础连接与底层数据解析通讯。
