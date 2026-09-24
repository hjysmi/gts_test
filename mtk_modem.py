#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Deep MediaTek Modem Subsystem (mtk_modem.py)
Consolidates MACE device connection, AT_TX message queue subscription, TX antenna
forcing, RX diversity switching, and ELG log saving into a single cohesive MtkModemSession.
Eliminates code duplication between mtk_rx.py and mtk_atc_md.py, and absorbs mtk_tx.py.
"""

import os
import sys
import re
import time
from typing import Optional, Tuple, List, Dict, Any

from adb_device import FlowResult

try:
    import mace
except ImportError:
    mace = None

# Mapping RX mode names to scenario IDs
RX_MODES_MAP = {
    "combine_4rx": 1,
    "combine_2rx": 6,
    "rx0": 2,
    "rx1": 3,
    "rx2": 4,
    "rx3": 5
}
ALLOWED_RX_MODES = list(RX_MODES_MAP.keys())

# Test Scenarios definition based on docs/antenna_rx_test_at_commands.html
SCENARIOS = {
    1: {
        "name": "combine_4rx (All checked)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,3,15,3,15,0'
        ]
    },
    2: {
        "name": "rx0 (Check 4 rx1)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,1,1,1'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,1,1,1,0'
        ]
    },
    3: {
        "name": "rx1 (Check 4 rx2)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,2,2,2,2'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,2,2,2,2,0'
        ]
    },
    4: {
        "name": "rx2 (Check rx1+rx3+rx1+rx3)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,4,1,4'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,4,1,4,0'
        ]
    },
    5: {
        "name": "rx3 (Check rx1+rx4+rx1+rx4)",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,15,3,15',
            'AT+EGMC=1,"rx_path",1,0,1,8,1,8'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,1,8,1,8,0'
        ]
    },
    6: {
        "name": "combine_2rx",
        "4g": [
            'AT+EGMC=1,"rx_path",1,0,3,3,3,3',
            'AT+EGMC=1,"rx_path",1,0,3,3,3,3'
        ],
        "nr": [
            'AT+EGMC=1,"nr_rx_path",1,0,3,3,3,3,0'
        ]
    }
}


class MtkModemSession:
    """
    Deep context manager for MediaTek MACE modem control, AT communication,
    antenna force switching, RX diversity testing, and diagnostic ELG logging.
    """
    def __init__(self, target_serial: str = "auto", database: str = "auto"):
        self.target_serial = str(target_serial).strip()
        self.database = database
        self.device = None
        self.itemset = None
        self._is_open = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        """
        Connect to MACE device and subscribe to AT_TX messages.
        """
        if self._is_open:
            return

        if mace is None:
            raise RuntimeError("MediaTek MACE SDK 未安装或未导入！请确认系统已配置 MACE Python 运行环境。")

        # MACE requires "auto" or a specific COM port. If an ADB serial is passed, use "auto".
        mace_target = "auto" if not self.target_serial or not str(self.target_serial).upper().startswith("COM") else self.target_serial
        print(f"\n[*] 正在连接 MACE 调制解调器设备 (Target={mace_target}, database={self.database})...")
        try:
            self.device = mace.connect_device(mace_target, database=self.database)
            print(f"[+] 成功连接至 MACE 设备: {self.device}")
        except Exception as e:
            err_msg = f"MACE 设备连接失败: {e}"
            print(f"[ERROR] {err_msg}")
            raise RuntimeError(err_msg)

        # 创建 itemset 并订阅 AT_TX 接收通道
        try:
            self.itemset = mace.create_itemset(self.device)
            self.itemset.subscribe(["AT_TX"])
            self.itemset.clear_queue()
        except Exception as e:
            print(f"[WARNING] 订阅 MACE AT_TX 消息队列异常: {e}")

        self._is_open = True

    def close(self):
        """
        Release MACE device and itemset subscriptions.
        """
        if not self._is_open:
            return

        print("\n[*] 正在释放 MACE 设备连接句柄...")
        self.itemset = None
        self.device = None
        self._is_open = False
        print("[+] MACE 会话已安全关闭。")

    def send_at_command(self, at_command: str, timeout: float = 5.0) -> Tuple[bool, List[str]]:
        """
        Send an AT command to MTK modem and collect the cleaned response lines.
        """
        if not self.device:
            return False, ["MACE 设备未连接"]

        if self.itemset:
            self.itemset.clear_queue()

        print(f"[*] 发送 AT 指令: {at_command}")
        try:
            self.device.send_at_command(at_command)
        except Exception as e:
            err_msg = f"发送 AT 指令异常: {e}"
            print(f"[ERROR] {err_msg}")
            return False, [err_msg]

        response_lines = []
        if not self.itemset:
            time.sleep(1)
            return True, ["OK"]

        start_time = time.time()
        while time.time() - start_time < timeout:
            item = self.itemset.get_next_item(100)  # 每 100ms 检查队列
            if item:
                msg = item.message
                clean_msg = re.sub(r"^\[AT_TX[^\]]*\]\s*", "", msg).strip()
                if clean_msg:
                    response_lines.append(clean_msg)
                    print(f"  <-- {clean_msg}")
                    if clean_msg in ("OK", "ERROR"):
                        break

        has_ok = any("OK" in line for line in response_lines)
        has_error = any("ERROR" in line for line in response_lines)
        success = has_ok and not has_error
        return success, response_lines

    def set_tx_antenna(self, rat: str, band: int, tx_state: int, rx_state: Optional[int] = None, ttps_port: int = 0) -> FlowResult:
        """
        Set MTK TX antenna forced configuration via EGMC AT command.
        """
        rat_upper = rat.upper()
        if rat_upper in ("LTE", "LTE_FDD"):
            # LTE FDD: rx_state must match tx_state
            rx_val = tx_state
            at_cmd = f'AT+EGMC=1,"lte_force_ttps",{band},{tx_state},{rx_val},{ttps_port}'
        elif rat_upper in ("LTE_TDD", "LTE TDD"):
            if rx_state is None:
                return FlowResult(False, "LTE_TDD 制式下 rx_state 为必填参数！")
            at_cmd = f'AT+EGMC=1,"lte_force_ttps",{band},{tx_state},{rx_state},{ttps_port}'
        elif rat_upper in ("NR", "NR_SA", "NR_NSA"):
            if rx_state is None:
                return FlowResult(False, "NR 制式下 rx_state 为必填参数！")
            at_cmd = f'AT+EGMC=1,"NR_force_TTPS",{band},{tx_state},{rx_state},{ttps_port}'
        else:
            return FlowResult(False, f"不支持的制式: '{rat}'")

        print(f"\n[*] 正在配置 MTK TX 天线强迫状态 (RAT={rat}, Band={band}, TxState={tx_state}, Port={ttps_port})...")
        success, lines = self.send_at_command(at_cmd)
        if success:
            print("[+] TX 天线状态设置成功。")
            return FlowResult(True, "")
        else:
            err_msg = f"TX 天线设置失败: {lines}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

    def set_rx_mode(self, rx_mode: str, rat: str = "4g") -> FlowResult:
        """
        Configure MTK RX diversity antenna mode (e.g., combine_4rx, rx0, rx1, rx2, rx3, combine_2rx).
        """
        mode_key = str(rx_mode).lower()
        if mode_key not in RX_MODES_MAP:
            return FlowResult(False, f"未知的 RX 模式: '{rx_mode}'，可用选项: {ALLOWED_RX_MODES}")

        scenario_id = RX_MODES_MAP[mode_key]
        scenario = SCENARIOS.get(scenario_id)
        if not scenario:
            return FlowResult(False, f"未找到场景 ID {scenario_id} 的测试指令配置")

        net_key = "4g" if rat.upper() in ("LTE", "LTE_FDD", "LTE_TDD", "4G") else "nr"
        commands = scenario.get(net_key, [])
        if not commands:
            return FlowResult(False, f"场景 '{scenario['name']}' 没有定义制式 '{net_key}' 的命令序列")

        print(f"\n[*] 正在执行 RX 分集接收切换: 场景={scenario['name']}, 制式={net_key.upper()}...")
        all_ok = True
        for cmd in commands:
            success, lines = self.send_at_command(cmd)
            if not success:
                all_ok = False
                print(f"[ERROR] 执行 RX 指令失败: {cmd}")
                break
            time.sleep(0.5)

        if all_ok:
            print(f"[+] 成功完成 RX 模式 '{rx_mode}' 的所有天线切换指令。")
            return FlowResult(True, "")
        else:
            err_msg = f"RX 模式 '{rx_mode}' 部分或全部指令执行失败。"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)

    def save_logs(self, out_dir: str = ".", log_file: str = "antenna_test_log.elg") -> FlowResult:
        """
        Persist active modem diagnostic logs to disk (.elg file).
        """
        if not self.device:
            return FlowResult(False, "MACE 设备未连接，无法保存日志")

        os.makedirs(out_dir, exist_ok=True)
        full_path = os.path.abspath(os.path.join(out_dir, log_file))
        print(f"\n[*] 正在保存 MTK Modem 诊断日志到: {full_path}...")
        try:
            self.device.save_log_file(full_path)
            print(f"[+] 诊断日志保存成功: {full_path}")
            return FlowResult(True, "")
        except Exception as e:
            err_msg = f"保存日志文件异常: {e}"
            print(f"[ERROR] {err_msg}")
            return FlowResult(False, err_msg)
