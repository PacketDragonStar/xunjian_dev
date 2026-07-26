"""B0 自定义检查器单元测试（纯 pytest，无需数据库）

运行（在能连数据库的环境中，或仅本文件不触库）：
    pytest app02/tests/test_custom_checks.py -v

本文件只 import app02.engine.pipeline 与 app02.custom_checks，
两者均不依赖 Django ORM，可在无 DB 的环境下直接跑。
"""
import re

import pytest

from app02.engine.pipeline import check_custom, _CUSTOM_CHECKERS, check_threshold
import app02.custom_checks  # 触发 @register_checker 注册


# ─────────────────────────────────────────────────────────
# 注册验证
# ─────────────────────────────────────────────────────────
def test_all_nine_checkers_registered():
    for name in ['check_fan', 'check_power', 'check_device', 'check_env',
                 'check_ifbrief', 'check_agg', 'check_arp', 'check_vrrp', 'check_nqa']:
        assert name in _CUSTOM_CHECKERS, f'{name} 未注册'


# ─────────────────────────────────────────────────────────
# 风扇 / 电源 / 单板：Normal 正常，Abnormal/Fault 异常
# ─────────────────────────────────────────────────────────
def test_fan_normal_and_fault():
    assert check_custom("Fan 1 State: Normal\nFan 2 State: Normal", '', {'func': 'check_fan'}, {}) == (True, '')
    ok, note = check_custom("Fan 1 State: Abnormal", '', {'func': 'check_fan'}, {})
    assert ok is False and '风扇' in note


def test_power_normal_and_fault():
    assert check_custom("Power 1 State: Normal", '', {'func': 'check_power'}, {}) == (True, '')
    ok, _ = check_custom("Power 2 State: Fault", '', {'func': 'check_power'}, {})
    assert ok is False


def test_device_normal_and_fault():
    assert check_custom("Slot 1  MPU  Normal", '', {'func': 'check_device'}, {}) == (True, '')
    ok, _ = check_custom("Slot 2  LPU  Fault", '', {'func': 'check_device'}, {})
    assert ok is False


# ─────────────────────────────────────────────────────────
# 环境温度
# ─────────────────────────────────────────────────────────
def test_env_temp_ok_and_over():
    sample = " Device      Current-Temp(C)  High-Thr(C)\n SDRAM       45               90"
    assert check_custom(sample, '', {'func': 'check_env'}, {}) == (True, '')
    hot = " Device      Current-Temp(C)  High-Thr(C)\n SDRAM       95               90"
    ok, note = check_custom(hot, '', {'func': 'check_env'}, {})
    assert ok is False and '60' not in note  # 用默认阈值60仍超，但提示应含温度
    assert '温度' in note


def test_env_fault_word():
    ok, _ = check_custom("Environment: Fault detected", '', {'func': 'check_env'}, {})
    assert ok is False


# ─────────────────────────────────────────────────────────
# 接口概要：物理 DOWN 数与 down_ok 期望值
# ─────────────────────────────────────────────────────────
IFBRIEF = """Interface            Link  Protocol
GE1/0/1              UP    UP
GE1/0/2              DOWN  DOWN
GE1/0/3              ADM   ADM
"""


def test_ifbrief_within_limit():
    assert check_custom(IFBRIEF, '', {'func': 'check_ifbrief'}, {'down_ok': 1}) == (True, '')


def test_ifbrief_exceeds_limit():
    ok, note = check_custom(IFBRIEF, '', {'func': 'check_ifbrief'}, {'down_ok': 0})
    assert ok is False and '1' in note


# ─────────────────────────────────────────────────────────
# 链路聚合
# ─────────────────────────────────────────────────────────
def test_agg_selected_ok():
    assert check_custom("GE1/0/1  Selected\nGE1/0/2  Selected", '', {'func': 'check_agg'}, {}) == (True, '')


def test_agg_unselected_anomaly():
    ok, note = check_custom("GE1/0/1  Selected\nGE1/0/2  Unselected", '', {'func': 'check_agg'}, {})
    assert ok is False and 'Unselected' in note


# ─────────────────────────────────────────────────────────
# ARP 冲突
# ─────────────────────────────────────────────────────────
def test_arp_no_conflict():
    assert check_custom("Total: 0 conflict records", '', {'func': 'check_arp'}, {}) == (True, '')
    assert check_custom("No user-ip-conflict record", '', {'func': 'check_arp'}, {}) == (True, '')


def test_arp_has_conflict():
    out = "1.1.1.1 conflict with 2.2.2.2 on GE1/0/1"
    ok, note = check_custom(out, '', {'func': 'check_arp'}, {})
    assert ok is False and '冲突' in note


# ─────────────────────────────────────────────────────────
# VRRP
# ─────────────────────────────────────────────────────────
def test_vrrp_master_match():
    assert check_custom("GE1/0/1  Master\nGE1/0/2  Backup", '', {'func': 'check_vrrp'}, {'vrrp_master': 1}) == (True, '')


def test_vrrp_master_mismatch():
    ok, note = check_custom("GE1/0/1  Master\nGE1/0/2  Master", '', {'func': 'check_vrrp'}, {'vrrp_master': 1})
    assert ok is False


def test_vrrp_initialize_anomaly():
    ok, _ = check_custom("GE1/0/1  Initialize", '', {'func': 'check_vrrp'}, {'vrrp_master': 0})
    assert ok is False


# ─────────────────────────────────────────────────────────
# NQA
# ─────────────────────────────────────────────────────────
def test_nqa_success():
    assert check_custom("Completion: success", '', {'func': 'check_nqa'}, {}) == (True, '')


def test_nqa_failed():
    ok, note = check_custom("Completion: failed", '', {'func': 'check_nqa'}, {})
    assert ok is False and '失败' in note


# ─────────────────────────────────────────────────────────
# 阈值（与自定义检查器协同验证 pipeline 入口）
# ─────────────────────────────────────────────────────────
def test_threshold_cpu_boundary():
    assert check_threshold(80.0, '', {'warning': 80, 'operator': '<'}, {}) == (True, '')
    ok, note = check_threshold(85.0, '', {'warning': 80, 'operator': '<'}, {})
    assert ok is False and '80' in note
