"""
PLCHaT Test Analysis Types

测试分析相关数据类型:
- TestIntent: 测试意图
- AssertionDef: 断言定义
- DistilledTrace: 蒸馏后的执行轨迹
- TestCaseReport: 测试分析报告
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict


# ======================= Test Intent =======================

@dataclass
class TestIntent:
    """测试意图"""
    source: str                           # "user" 或 "llm_generated"
    description: str                      # 意图描述
    safety_dimensions: List[str] = field(default_factory=list)    # 安全测试维度
    functional_dimensions: List[str] = field(default_factory=list)  # 功能测试维度
    expected_behavior: str = ""           # 预期行为
    key_variables: List[str] = field(default_factory=list)  # 关键变量


# ======================= Assertion =======================

@dataclass
class AssertionDef:
    """断言定义"""
    variable: str                          # 监控变量
    condition: str                         # 条件 (如 "<= 10", "!= 16#8001")
    failure_meaning: str                   # 失败含义 (如"堆栈溢出", "参数错误")
    category: str                          # "safety" 或 "functional"
    severity: str = "warning"              # "critical", "warning", "info"


# ======================= Distilled Trace =======================

@dataclass
class StateTransition:
    """状态转换"""
    cycle: int
    variable: str
    old_value: Any
    new_value: str


@dataclass
class AssertionFailure:
    """断言失败"""
    cycle: int
    assertion_variable: str
    actual_value: Any
    condition: str
    failure_meaning: str


@dataclass
class DistilledTrace:
    """蒸馏后的执行轨迹"""
    total_cycles: int
    compressed_cycles: int                    # 压缩后保留的周期数

    execution_summary: str                     # 执行摘要 (自然语言)
    key_events: List[dict] = field(default_factory=list)
    state_transitions: List[StateTransition] = field(default_factory=list)
    assertion_failures: List[AssertionFailure] = field(default_factory=list)

    compression_ratio: float = 0.0             # 压缩比率


# ======================= Tools =======================

@dataclass
class CompressedSegment:
    """压缩后的时间段"""
    start_cycle: int
    end_cycle: int
    state: dict           # 该时段的状态
    is_stable: bool                 # 是否为稳定状态


@dataclass
class StateChange:
    """状态变化"""
    cycle: int
    variable: str
    old_value: Any
    new_value: Any


@dataclass
class CyclePattern:
    """周期模式"""
    description: str                   # 模式描述
    cycle_range: str                   # 周期范围 (如 "1-5")
    count: int                        # 重复次数


# ======================= Report =======================

@dataclass
class TestCaseReport:
    """测试用例分析报告"""
    case_id: str

    # LLM分析结果
    test_scenario: str                      # 测试场景描述
    findings: List[str] = field(default_factory=list)      # 发现的问题
    root_cause: str = ""                    # 根本原因分析
    severity: str = "info"                  # "critical", "warning", "info"
    fix_suggestion: str = ""                # 修复建议

    # 支持数据
    execution_summary: str = ""
    assertion_results: List[str] = field(default_factory=list)

    # 元数据
    analysis_time_sec: float = 0.0
    confidence_score: float = 0.0


@dataclass
class TestCaseAnalysisReport:
    """测试用例分析报告（完整版） - v1 完整四部分报告"""

    # 1. 测试用例输入摘要
    test_case_count: int                    # 测试用例总数
    test_case_types: Dict[str, int] = field(default_factory=dict)  # 测试用例类型分布

    # 2. 功能意义分析
    functional_points: List[str] = field(default_factory=list)     # 识别的功能点
    design_quality: str = "unknown"         # "reasonable" | "unexpected" | "vulnerable"
    risk_assessment: str = "unknown"         # "high" | "medium" | "low"
    anomaly_behaviors: List[str] = field(default_factory=list)     # 发现的异常行为

    # 3. 测试用例质量评估
    coverage_summary: Dict[str, float] = field(default_factory=dict)  # 行/分支/函数覆盖率
    uncovered_regions: List[str] = field(default_factory=list)        # 未覆盖的代码区域
    quality_score: int = 0                 # 质量评分 0-100
    completeness: str = "unknown"           # "sufficient" | "moderate" | "insufficient"

    # 4. 下一步建议
    coverage_breakthrough: List[str] = field(default_factory=list)   # 覆盖率突破建议
    suggested_inputs: List[str] = field(default_factory=list)        # 建议的测试输入
    priority_targets: List[str] = field(default_factory=list)         # 优先测试目标

    # 元数据
    execution_status: str = "unknown"
    assertion_results: List[str] = field(default_factory=list)
    mode: str = "unknown"                   # "A_coverage" | "B_assertion" | "combined"


# ======================= Minimization Comparison =======================

@dataclass
class MinComparisonResult:
    """测试用例最小化对比结果

    展示：一个长测试用例 → 一个短测试用例，触发同一个 assertion，
    帮助用户理解问题根因（root cause）。
    """
    program_id: str
    assertion_message: str

    # 原始输入
    original_cycles: int
    original_values: int
    original_text: str                       # sparse_timeline 文本格式

    # ddmin 缩减结果
    ddmin_values: int
    ddmin_text: str
    ddmin_cycles: int
    ddmin_oracle_calls: int
    ddmin_assertion_preserved: bool
    ddmin_reduction_ratio: float

    # HDD 缩减结果
    hdd_values: int
    hdd_text: str
    hdd_cycles: int
    hdd_oracle_calls: int
    hdd_assertion_preserved: bool
    hdd_reduction_ratio: float

    # 覆盖率对比 (line / branch / region)
    original_coverage: Dict[str, str] = field(default_factory=dict)   # {"line": "54.29%", "branch": "25.00%", ...}
    minimized_coverage: Dict[str, str] = field(default_factory=dict)

    # 元数据
    execution_time_sec: float = 0.0
    log_dir: str = ""                       # 详细日志目录
