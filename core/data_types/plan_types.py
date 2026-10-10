"""
PLCHaT Plan and Strategy Types
Data structures for planning, execution strategies, and agent coordination.
"""

import uuid
from enum import Enum
from typing import Any, List, Dict, Optional, Set
from pydantic import BaseModel, Field, model_validator
from dataclasses import dataclass, field


# =========================================================================
# 1. Core Enum Definitions (The Domain Constraints)
# =========================================================================

class TaskArchetype(str, Enum):
    P_ALG = "P_alg"
    P_SEQ = "P_seq"
    P_TIME = "P_time"
    GENERAL = "General"
    SATURATED = "SATURATED"
    # [Neuro-Symbolic] New: Vulnerability exploit highest priority archetype
    VULNERABILITY_EXPLOIT = "VULNERABILITY_EXPLOIT"


class TargetAnchorType(str, Enum):
    """Context anchor type"""
    CODE_SNIPPET = "code_snippet"         # Specific AST code snippet
    FUNCTIONAL_STATE = "functional_state" # Macro functional state
    BOUNDARY_VAR = "boundary_variable"    # Boundary variable
    GLOBAL = "global_context"             # [New patch] Global context/stagnant state


class SystemDirectiveType(str, Enum):
    """
    System-level directives (Orchestrator Control Signals).
    Planner directly takes over Orchestrator lifecycle through this field.
    """
    CONTINUE = "CONTINUE"             # Normal progress, pass actionable_nodes to Generator
    STOP_SATURATED = "SATURATED"      # Coverage stagnation or strategy exhaustion, require terminating Fuzzing
    STOP_SUCCESS = "SUCCESS"          # Achieved perfect coverage, require victorious exit
    FALLBACK_EXPLORE = "FALLBACK"     # Exception or deadlock, require Orchestrator to reset state for exploration


@dataclass
class TargetObservation:
    """
    Data Transfer Object (DTO): Built by main control loop (Orchestrator/Sense Phase),
    contains all required context for current stagnation node, passed unidirectionally to Planner to avoid cross-component coupling.
    """
    target_identifier: str       # E.g.: "LinearizeValue_Line42"
    spatial_context: str         # Context extracted by static analyzer (e.g., AST slice)
    temporal_context: str        # Failure reason or Trace extracted by evaluator
    required_pre_states: List[str] # Required prerequisite state identifiers


class ExecutionStrategy(str, Enum):
    SYMBOLIC_SOLVING = "symbolic_guard_solving"
    BOUNDARY_MUTATION = "boundary_value_mutation"
    SEQUENCE_SUMMARY = "semantic_sequence_summary"
    STATE_TRACKING = "state_transition_tracking"

    # Core exploration strategies
    RANDOM_FUZZING = "exploratory_random_fuzzing"
    # [New alignment patch] Explicitly fill enum attributes referenced in test code to avoid AttributeError
    EXPLORATORY_RANDOM_FUZZING = "exploratory_random_fuzzing"

    CRASH_MINIMIZATION = "crash_minimization"
    ADVERSARIAL_INJECTION = "adversarial_boundary_injection"
    CALL_FUZZING_BREAKTHROUGH = "call_fuzzing_breakthrough"

    # [Neuro-Symbolic] New: Tactical guidance and vulnerability concentration strategies
    DIRECTED_VULNERABILITY_MUTATION = "directed_vulnerability_mutation"

    @classmethod
    def safe_get(cls, strategy_name: str) -> str:
        """
        Bulletproof mechanism: Try various ways to match strategy.
        If no match, directly return original name string to avoid Pydantic or system-level crash.
        """
        if not isinstance(strategy_name, str):
            return strategy_name

        # 1. Try direct value match, e.g., "symbolic_guard_solving"
        try:
            return cls(strategy_name).value
        except ValueError:
            pass

        # 2. Try attribute name match, e.g., "SYMBOLIC_SOLVING"
        strategy_upper = strategy_name.upper()
        if hasattr(cls, strategy_upper):
            return getattr(cls, strategy_upper).value

        # 3. Common hallucination alias tolerance (Fuzzy Matching)
        if "RANDOM" in strategy_upper and "EXPLORATORY" in strategy_upper:
            return cls.RANDOM_FUZZING.value

        # 4. Ultimate fallback: directly return original string, pass tolerance to LLM or subsequent routing logic
        return strategy_name


class NodeStatus(str, Enum):
    """Node status lifecycle in the plan graph"""
    PENDING = "PENDING"     # Waiting for execution (prerequisites met or no dependencies)
    BLOCKED = "BLOCKED"     # Blocked (prerequisites not completed)
    ACTIVE = "ACTIVE"       # Being processed by Generator
    COMPLETED = "COMPLETED" # Successfully break through
    FAILED = "FAILED"       # Execution failed (e.g., Exception)
    UNSAT = "UNSAT"         # Mathematically unreachable or unsolvable


# =========================================================================
# 2. LLM Structured Output Contract (The DVP Payload using Pydantic)
# Purpose: Force LLM to output according to this Schema, reject any vague natural language plans.
# =========================================================================

class DiagnosisContext(BaseModel):
    archetype: TaskArchetype = Field(..., description="The fundamental nature of the current coverage bottleneck.")
    bottleneck_analysis: str = Field(..., description="Analysis of why the fuzzer is stuck based on evaluator feedback.")


class IntentContext(BaseModel):
    goal_description: str = Field(..., description="The high-level objective for this specific step.")
    spatial_context_summary: str = Field(..., description="Summary of the involved guard conditions and variables.")
    temporal_context_summary: str = Field(..., description="Summary of the historical execution failures or traces.")


class ActionRouting(BaseModel):
    selected_strategy: ExecutionStrategy = Field(..., description="The strict tool/strategy to deploy.")
    expected_cycles: int = Field(default=1, description="Expected scan cycles required to fulfill this action.")


class PlanPayload(BaseModel):
    """Dynamic Verification Plan carrier"""
    goal: str = Field("", description="Legacy flat access to intent.goal_description")
    diagnosis: DiagnosisContext
    intent: IntentContext
    target_type: TargetAnchorType
    target_details: str = Field(..., description="The rich context anchor (e.g., AST snippet or state description).")
    action_routing: ActionRouting
    diagnostic_notes: Optional[str] = Field(None, description="Reflexion notes to avoid repeating previous mistakes.")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def sync_goal_attribute(self) -> 'PlanPayload':
        """
        [Hardened Sync] Replace unstable __init__, ensure goal attribute is correctly synchronized
        after instantiation and deserialization. Solve 'PlanPayload' object has no attribute 'goal' error.
        """
        if not self.goal and self.intent and hasattr(self.intent, 'goal_description'):
            # Use object.__setattr__ to bypass possible Pydantic attribute freezing restrictions
            object.__setattr__(self, 'goal', self.intent.goal_description)
        return self


# =========================================================================
# 3. Plan Graph Data Structure (Verification Plan Graph)
# Purpose: Maintain DAG (Directed Acyclic Graph) for multi-step plans, provide minimal CURD and state scheduling interfaces.
# =========================================================================

@dataclass
class TargetObligation:
    """A node in the graph: represents a specific exploration/editing obligation"""
    id: str
    target_identifier: str  # E.g.: specific branch_id or line number marker, for deduplication
    payload: PlanPayload    # Specific execution strategy (LLM generated)
    status: NodeStatus = NodeStatus.PENDING

    # Diagnosis and history records
    retry_count: int = 0
    history_logs: List[str] = field(default_factory=list)


class VerificationPlanGraph:
    """Global state transition and plan graph manager"""

    def __init__(self):
        # Node storage (Node ID -> Node)
        self.nodes: Dict[str, TargetObligation] = {}
        # Dependency edge maintenance: node_id -> dependent_node_ids (A must complete before B can execute)
        self.successors: Dict[str, Set[str]] = {}
        # Reverse dependency maintenance: node_id -> prerequisite_node_ids (query if node can execute)
        self.predecessors: Dict[str, Set[str]] = {}

    # --- C: Create (Add nodes and edges) ---
    def add_node(self, target_identifier: str, payload: PlanPayload) -> TargetObligation:
        """Register a new obligation node. If exists and not completed, update it."""
        # Prevent adding duplicate nodes with same target
        existing_node = self.get_node_by_target(target_identifier)
        if existing_node and existing_node.status not in [NodeStatus.COMPLETED, NodeStatus.UNSAT]:
            # Update Payload (dynamic replanning/Reflexion)
            existing_node.payload = payload
            existing_node.retry_count += 1
            existing_node.status = NodeStatus.PENDING
            self._update_graph_status()
            return existing_node

        node_id = f"node_{uuid.uuid4().hex[:8]}"
        new_node = TargetObligation(id=node_id, target_identifier=target_identifier, payload=payload)
        self.nodes[node_id] = new_node
        self.successors[node_id] = set()
        self.predecessors[node_id] = set()

        self._update_graph_status()
        return new_node

    def add_dependency(self, prereq_node_id: str, dependent_node_id: str):
        """Add directed edge: prereq_node -> dependent_node"""
        if prereq_node_id in self.nodes and dependent_node_id in self.nodes:
            self.successors[prereq_node_id].add(dependent_node_id)
            self.predecessors[dependent_node_id].add(prereq_node_id)
            self._update_graph_status()

    # --- U: Update (Update status) ---
    def update_node_status(self, node_id: str, new_status: NodeStatus, log_msg: Optional[str] = None):
        """Update node status, automatically cascade update dependent node statuses"""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.status = new_status
            if log_msg:
                node.history_logs.append(log_msg)
            # If node completes or fails, may trigger downstream node status changes (e.g., from BLOCKED to PENDING)
            self._update_graph_status()

    # --- R: Retrieve / Read (Query scheduling interface) ---
    def get_node(self, node_id: str) -> Optional[TargetObligation]:
        return self.nodes.get(node_id)

    def get_node_by_target(self, target_identifier: str) -> Optional[TargetObligation]:
        for node in self.nodes.values():
            if node.target_identifier == target_identifier:
                return node
        return None

    def get_actionable_nodes(self) -> List[TargetObligation]:
        """Core scheduling method: get all nodes currently executable by Generator"""
        actionable = []
        for node in self.nodes.values():
            if node.status == NodeStatus.PENDING:
                actionable.append(node)
        # Sort by retry count, prioritize nodes with fewer retries
        actionable.sort(key=lambda x: x.retry_count)
        return actionable

    # --- Internal maintenance tools ---
    def _update_graph_status(self):
        """Traverse graph, update node PENDING/BLOCKED status based on prerequisite dependencies"""
        for node_id, node in self.nodes.items():
            # Only evaluate dependencies when node itself is in PENDING or BLOCKED status
            if node.status in [NodeStatus.PENDING, NodeStatus.BLOCKED]:
                prereqs = self.predecessors.get(node_id, set())
                # If all prerequisite nodes are COMPLETED
                if all(self.nodes[p].status == NodeStatus.COMPLETED for p in prereqs):
                    node.status = NodeStatus.PENDING
                else:
                    node.status = NodeStatus.BLOCKED


# =========================================================================
# 4. Agent-level Standard Output Contract (Agent Standard Output)
# =========================================================================

@dataclass
class PlannerOutput:
    """
    Planner Agent's final structured output.
    Orchestrator only uses this object to decide system's next move.
    """
    directive: SystemDirectiveType        # Decide if Orchestrator continues or exits
    actionable_nodes: List[TargetObligation]    # Task nodes to execute (if directive is STOP, usually empty)
    message: str                                # Log message passed to Orchestrator for printing or recording
    metadata: Dict[str, Any] = field(default_factory=dict) # Carries complete Time & Token bill for this Planner call
