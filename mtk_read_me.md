# MTK Antenna Force & RX Test End-to-End Orchestration Tool (mtk_main.py)

本工具专为 **MediaTek (MTK)** 平台手机在开发、射频调试（RF Test）或量产测试阶段设计，旨在通过 **MACE API (AT 串口)** 与 **ADB 命令行**，全自动执行手机 Logger 状态切换、网络制式更改、发射（TX）及接收（RX）天线强迫设定的连贯测试编排。

---

## 🚀 核心工作流 (8 大测试步骤)

当运行 `mtk_main.py` 时，脚本会安全且严格地按照以下顺序执行 8 步编排：

```
[开始] ──> 1. 停止 MTK Logger ──> 2. 切换 Modem 为 USB 模式 ──> 3. 开启 MTK Logger 
         └──> [建立 MACE 连接] ──> 4. 切换 Android 网络类型 (LTE/NR/Default) 
         └──> 5. 强迫 TX 天线切换 
         └──> 6. 强迫 RX 天线分集切换 
         └──> 7. 持久化调制解调器诊断日志 (.elg) ──> 8. 停止 MTK Logger ──> [结束]
```

---

## 📋 参数解读 (Parameter Interpretation)

无论是通过**命令行（CLI）** 还是在代码中传递 **`params` 字典**，所有配置参数都需遵循以下严格的规则及校验。

| 参数名 (CLI) | 字典 Key (Dict) | 类型 (Type) | 必填 | 取值范围 / 选项 | 物理含义与校验规则 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `--serial` | `"serial"` | `str` | **是** | *非空字符串* | **目标 ADB 序列号**。<br>• 匹配手机的 adb 序列号（如 `NAVR120201`）以供精准下发控制。 |
| `--rat` | `"rat"` | `str` | **是** | `LTE` (FDD)<br>`LTE_TDD`<br>`NR_SA` (或 `NR_ONLY`)<br>`NR_NSA` (或 `NR`, `NR_LTE`) | **通信制式（已合并原 --network-mask，自动配置网络掩码）**。<br>• `LTE` / `LTE_FDD`: 4G FDD 模式，自动配置掩码 `LTE_ONLY`<br>• `LTE_TDD`: 4G TDD 模式，自动配置掩码 `LTE_ONLY`<br>• `NR_SA` / `NR_ONLY`: 5G SA 独立组网，自动配置掩码 `NR_ONLY`<br>• `NR_NSA` / `NR_LTE` / `NR`: 5G NSA 模式，自动配置掩码 `NR_LTE`（保留 4G 锚点避免脱网） |
| `--band` | `"band"` | `int` | **是** | `1 ~ 255` | **测试频段号**。<br>• **LTE 强校检**：如果 RAT 为 `LTE`，频段必须属于 FDD 频段；如果为 `LTE_TDD`，则必须属于 TDD 频段。 |
| `--tx-state` | `"tx_state"` | `int` | **是** | `0 ~ 23`, `255` | **Tx TAS State (发射天线选择状态)**。<br>• 取值代表射频给定的状态切换索引（不等于物理天线编号）。`255` 代表默认（Default）。 |
| `--rx-state` | `"rx_state"` | `int` | *条件* | `0 ~ 23`, `255` | **Rx TAS State (接收天线选择状态)**。<br>• **LTE (FDD)** 下：**绝对不能**传入此参数，底层会自动使用 `tx_state` 填充 Rx 状态。<br>• **LTE_TDD / NR** 下：**必须**传入此参数。 |
| `--ttps-port` | `"ttps_port"` | `int` | **是** | `0`, `1` | **TTPS TX 物理端口**。<br>• 选择射频发射的主通道/副通道端口。 |
| `--sim-slot` | `"sim_slot"` | `int` | **是** | `0`, `1` | **SIM 卡槽**。<br>• `0` 代表卡 1 (SIM 1)，`1` 代表卡 2 (SIM 2)。 |
| `--rx-mode` | `"rx_mode"` | `str` | **是** | `combine_4rx`, `combine_2rx`,<br>`rx0`, `rx1`, `rx2`, `rx3` | **RX 接收天线测试模式**。<br>• `combine_4rx`: 4Rx 全勾选模式<br>• `combine_2rx`: 2Rx 全勾选模式 (Rx12+Rx12+Rx12+Rx12)<br>• `rx0`: Rx0 强迫单通测试<br>• `rx1`: Rx1 强迫单通测试<br>• `rx2`: Rx2 强迫双接收分集<br>• `rx3`: Rx3 强迫分集测试 |
| `--out-dir` | `"out_dir"` | `str` | 否 | *有效目录路径* | **日志保存目录**（默认：`.` 当前运行目录）。 |
| `--log-file` | `"log_file"` | `str` | 否 | *文件名*（如 `antenna_test_log.elg`） | **诊断日志文件名**（默认：`antenna_test_log.elg`）。 |
| *(已合并)*<br>`--network-mask` | `"network_mask"` | `str` | *已移除* | `LTE_ONLY`, `NR_ONLY`, `NR_LTE`, `DEFAULT` | **已合并进 `--rat` 自动推导，CLI 命令行参数已移除**。<br>• 仅限 Python 字典调用时可选传入；若显式传入将自动校验其与 `rat` 是否冲突。 |

### 参数解析详情

`AT+EGMC=1,"lte_force_ttps",1,0,0,1,1` 的参数格式与内部结构体定义（对应 `el1_uac_tx_path_switch_req_struct`）映射如下：

| 参数位置 | 参数值 | 对应字段 | 含义说明 |
| :--- | :--- | :--- | :--- |
| op | 1 | 操作模式 | 1 为 Set（配置）模式 |
| config_str | "lte_force_ttps" | 配置名称 | LTE 强制 TTPS 设置 |
| 参数 1 | 1 | mode | 开关控制：1 表示 Enable（开启），0 表示 Disable |
| 参数 2 | 0 | tx_state | 期望的 Tx State（范围 0 ~ 31） |
| 参数 3 | 0 | rx_state | 期望的 Rx State（范围 0 ~ 31） |
| 参数 4 | 1 | tx_path / ttps_port | 期望强制生效的 TTPS 天线端口/发射路径（0 为 Tx Path 0，1 为 Tx Path 1） |
| 参数 5 | 1 | band | 指定生效的频段（如 Band 1） |

#### 核心对应关系：ttps_port 与 Tx Path

在 MTK 基带的 TAS/UTAS（上行发射天线分集与切换）架构中，AT 指令中的 `ttps_port` 直接对应物理射频的 **Tx Path（发射路径）**：

| 参数 / 配置 | 对应的 UTAS 发射路径 | Log 中对应的候选天线字段 |
| :--- | :--- | :--- |
| **`ttps_port = 0`** | **Tx Path 0** | `Utas TxCandidAnt Info Tx Path0` |
| **`ttps_port = 1`** | **Tx Path 1** | `Utas TxCandidAnt Info Tx Path1` |

##### 实际生效验证（来源于 `l1_trace.txt` 日志）：

| Type | Index | FRC (64us) | Time | Module | Message | Comment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| L1 | 2049242 | 367364776 | 21:19:42.589056 2026/9/24 | MML1_UAC_PUBLIC | `[MML1][UTAS][SPAT][PUBLIC][0]MEAS_PRMS: cc_idx=0, band: B1, PHR=0, SNR[25, 255, 255, 255], RSRP[-88, 255, 255, 255], RX_ANT: [ANT2, ANT8, ANT9, ANT6], TX_ANT: ANT2` | 证实 ttps_port=0 下发后生效为 ANT2 |

```text
                    ┌── 射频开关 ───► ANT2 (物理天线2)
[Tx Path 0 链路] ───┤
(ttps_port = 0)     └── 射频开关 ───► ANT9 (物理天线9)

[Tx Path 1 链路] ───► 固定/独立通路 ─► ANT8 (物理天线8)
(ttps_port = 1)
```

结合前面日志中的 `Utas TxCandidAnt Info`：
* **Tx Path 0 (`ttps_port = 0`)**：硬件上连到了支持天线切换的射频多路开关，其候选天线池（Candidate Antennas）为 ANT2 和 ANT9。
* **Tx Path 1 (`ttps_port = 1`)**：硬件上走的是另一组射频通路，其候选天线池仅有 ANT8。

---

## ⚠️ 参数强校验规则 (Validation Rules)

本脚本在执行首步操作前，会通过 `validate_params()` 启动强类型和业务规则校检，以下任意不匹配项均会**立刻拦截并安全报错**：

1. **目标设备序列号 (Serial) 校验**:
   * `--serial` 必须为非空字符串，用于确保针对指定物理手机精准执行 ADB 指令、网络掩码切换和 MACE 调制解调器连接。
2. **制式与网络掩码自适应推导与防冲突**:
   * 无需手动传入网络掩码，系统根据 `--rat` 自动完成推导：
     * `LTE` / `LTE_TDD` $\rightarrow$ 自动绑定 `LTE_ONLY`
     * `NR_SA` $\rightarrow$ 自动绑定 `NR_ONLY`
     * `NR_NSA` / `NR` $\rightarrow$ 自动绑定 `NR_LTE`（保障 4G LTE 锚点驻留）
   * 若外部调用时同时传入了 `network_mask`，将启动**兼容互斥校检**（例如传入 `rat="LTE"` 但 `network_mask="NR_ONLY"` 将直接拦截报错）。
3. **频段与双工错配拦截 (LTE FDD vs TDD Band)**:
   * **LTE (FDD)** 常用频段集合：`{1, 2, 3, 4, 5, 7, 8, 12, 13, 14, 17, 18, 19, 20, 21, 25, 26, 28, 30, 31, 32, 66, 71}`
   * **LTE TDD** 常用频段集合：`{34, 37, 38, 39, 40, 41, 42, 43, 46, 48}`
   * *例：若 `--rat LTE` (FDD) 但传入 `--band 41`，程序将报错中断。*
4. **接收天线状态 (Rx TAS State) 隔离规则**:
   * **LTE (FDD)** 制式下：程序硬性限制**不得传入** `rx_state`。若强行传入将抛出错误。
   * **LTE TDD** 和 **NR** 制式下：程序硬性限制**必须传入** `rx_state`。若遗漏将抛出错误。
5. **接口取值域验证**:
   * 确保卡槽、端口、天线档位与场景 ID 在出厂硬编码安全取值范围内。

---

## 💻 调用示例 (Execution Examples)

### 1. 命令行调用 (CLI Options)

根据具体测试制式选择以下合理的调用指令：

#### A. LTE FDD 黄金频段 3 强迫发射与分集测试
*发射和接收天线均强制设定为状态 `1`，选择端口 `0`，网络锁定 4G，SIM卡1*
```bash
python mtk_main.py --serial NAVR120201 --rat LTE --band 1 --tx-state 0 --ttps-port 1 --sim-slot 0 --rx-mode rx0
```

#### B. LTE TDD 频段 41 强迫发射与分集测试
*时分双工下，强迫发射为状态 `2`，强制接收为状态 `0`（收发分离），网络锁定 4G，SIM卡1*
```bash
python mtk_main.py --serial NAVR120201 --rat LTE_TDD --band 41 --tx-state 2 --rx-state 0 --ttps-port 1 --sim-slot 0 --rx-mode rx0
```

#### C. 5G SA 频段 78 强迫发射与分集测试
*纯 5G 独占网络锁定，强迫发射为状态 `3`，强制接收为状态 `1`，SIM卡1*
```bash
python mtk_main.py --serial NAVR120201 --rat NR_SA --band 78 --tx-state 3 --rx-state 1 --ttps-port 0 --sim-slot 0 --rx-mode rx1
```

#### D. 5G NSA 频段 78 强迫发射与分集测试
*保留 4G 锚点避免脱网，强迫发射为状态 `3`，强制接收为状态 `1`，SIM卡1*
```bash
python mtk_main.py --serial NAVR120201 --rat NR_NSA --band 78 --tx-state 3 --rx-state 1 --ttps-port 0 --sim-slot 0 --rx-mode rx1
```

---

### 2. Python 模块字典传参调用 (Module Integration)

可以在其他 Python 测试脚本、量产套件或 Web 框架中直接集成该工作流。

```python
import sys
from mtk_main import validate_params, run_orchestration_flow

# 1. 准备您的测试字典类参数 (如 5G 场景测试，无需显式指定 network_mask，自动由 rat 推导)
test_config = {
    "serial": "NAVR120201",
    "rat": "NR_NSA",
    "band": 78,
    "tx_state": 1,
    "rx_state": 3,
    "ttps_port": 0,
    "sim_slot": 0,
    "rx_mode": "rx0"
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
* **`mtk_modem.py`**：【深模块】联发科调制解调器底层驱动模块（`MtkModemSession` 上下文管理器），深度收敛 MACE 设备连接、AT_TX 队列订阅与响应解析、全制式 TX 强迫、RX 分集测试场景命令目录以及 ELG 调制解调器日志持久化。
* **`adb_device.py`**：【深模块】统一 Android 设备控制层（`AdbDevice`），封装在线与授权守卫、网络制式掩码切换、MTK LoggerUI 广播控制（stop/start/switch_usb）。
* **`mtk_tx.py`** / **`mtk_rx.py`** / **`mtk_atc_md.py`**：向后兼容的独立脚本，支持单步骤调试。
* **`android_network_manager.py`**：底层网络类型掩码常量定义与通用辅助。
