"""
PLCHaT Core Base Types
Standardized base types for complex data structures.
"""

from dataclasses import dataclass, asdict, is_dataclass, field
from typing import (
    List, Dict, Any, Optional, Literal, Set,
    Union, TypeVar, Type, get_type_hints,
    get_origin, get_args
)
from enum import Enum

# A type variable to represent any class that inherits from BaseType.
T = TypeVar('T', bound='BaseType')


class BaseType:
    """
    Base class for all dataclass models to provide common methods for JSON
    serialization and deserialization.
    """

    def _to_json(self) -> str:
        return self._to_dict()

    def _to_dict(self) -> Dict[str, Any]:
        """
        Recursively converts the dataclass and its nested dataclasses into a
        dictionary for JSON serialization.
        """
        result = {}
        if not is_dataclass(self):
            return self.__dict__

        for key, value in asdict(self).items():
            if isinstance(value, BaseType):
                result[key] = value._to_dict()
            elif isinstance(value, list):
                result[key] = [item._to_dict() if isinstance(item, BaseType) else item for item in value]
            elif isinstance(value, dict):
                result[key] = {k: v._to_dict() if isinstance(v, BaseType) else v for k, v in value.items()}
            else:
                result[key] = value
        return result

    @classmethod
    def _from_json(cls: Type[T], json_data: str) -> T:
        return cls._from_dict(json_data)

    @classmethod
    def _from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """
        Recursively converts a dictionary into a dataclass and its nested
        dataclasses, handling complex types.
        """
        if not is_dataclass(cls):
            obj = cls()
            for key, value in data.items():
                setattr(obj, key, value)
            return obj

        processed_data = {}
        type_hints = get_type_hints(cls)

        for field_name, field_type in type_hints.items():
            if field_name not in data:
                continue

            actual_type = field_type
            if get_origin(field_type) is Union:
                args = get_args(field_type)
                if len(args) == 2 and type(None) in args:
                    actual_type = args[0] if args[1] is type(None) else args[1]

            if get_origin(actual_type) is list:
                list_args = get_args(actual_type)
                if list_args:
                    actual_type = list_args[0]

            is_base_type = isinstance(actual_type, type) and issubclass(actual_type, BaseType)

            value = data[field_name]

            if get_origin(field_type) is Optional:
                field_type = get_args(field_type)[0]

            if get_origin(field_type) is list:
                item_type = get_args(field_type)[0]
                if isinstance(item_type, type) and issubclass(item_type, BaseType) and isinstance(value, list):
                    processed_data[field_name] = [item_type._from_dict(item) for item in value]
                else:
                    processed_data[field_name] = value
            elif isinstance(field_type, type) and issubclass(field_type, BaseType) and isinstance(value, dict):
                processed_data[field_name] = field_type._from_dict(value)
            elif isinstance(field_type, type) and issubclass(field_type, Enum) and isinstance(value, str):
                processed_data[field_name] = field_type(value)
            else:
                processed_data[field_name] = value

        return cls(**processed_data)

    def get_value(self, key: str) -> Any:
        """Gets the value of a field."""
        if hasattr(self, key):
            return getattr(self, key)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def set_value(self, key: str, value: Any):
        """Sets the value of a field, with type checking for dataclasses."""
        if not hasattr(self, key):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

        field_type = get_type_hints(self.__class__).get(key)

        if isinstance(value, dict):
            origin_type = getattr(field_type, '__origin__', field_type)
            args = getattr(field_type, '__args__', ())

            if origin_type is Union and is_dataclass(args[0]) and issubclass(args[0], BaseType):
                setattr(self, key, args[0]._from_dict(value))
            elif is_dataclass(field_type) and issubclass(field_type, BaseType):
                setattr(self, key, field_type._from_dict(value))
            else:
                setattr(self, key, value)
        else:
            setattr(self, key, value)

    def update_with_dict(self, data: Dict[str, Any]):
        """Updates the object's fields with a dictionary, handling nested objects."""
        for key, value in data.items():
            if hasattr(self, key):
                field_type = get_type_hints(self.__class__).get(key)
                current_value = getattr(self, key)

                if isinstance(current_value, BaseType) and isinstance(value, dict):
                    current_value.update_with_dict(value)
                elif isinstance(current_value, list) and isinstance(value, list):
                    new_list = []
                    list_type = get_type_hints(self.__class__).get(key)
                    item_type = getattr(list_type, '__args__', [None])[0]

                    for item in value:
                        if isinstance(item, dict) and is_dataclass(item_type) and issubclass(item_type, BaseType):
                            new_list.append(item_type._from_dict(item))
                        else:
                            new_list.append(item)
                    setattr(self, key, new_list)
                else:
                    self.set_value(key, value)

    def delete_value(self, key: str):
        """Deletes a field's value by setting it to a default value."""
        if not hasattr(self, key):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

        fields = {f.name: f for f in self.__dataclass_fields__.values()}
        field_info = fields.get(key)

        if field_info:
            if field_info.default is not field:
                setattr(self, key, field_info.default)
            elif field_info.default_factory is not field:
                setattr(self, key, field_info.default_factory())
            else:
                setattr(self, key, None)


@dataclass
class TestStep:
    """A single test step with inputs, duration, and forced variables."""
    inputs: Dict[str, Any]
    duration: int = 1
    force_vars: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OracleViolation(BaseType):
    """Represents a violation detected by the oracle."""
    test_item_id: str
    name: str
    severity: Literal["low", "medium", "high", "critical"]
    reason: str
    evidence: Dict[str, Any]


@dataclass
class AnalysisReport(BaseType):
    """Represents an analysis report from test execution."""
    is_interesting: bool
    vulnerability_type: str
    details: str
    coverage_gain: Dict[str, float]
    oracle_violations: List[OracleViolation]
    suggestions: List[str]


@dataclass
class InitialState(BaseType):
    """
    Initial state for incremental simulation state continuity.

    Note: VAR_INPUT is not persisted by design - it's synthesized as empty
    when converting to PLCVarState.
    """
    VAR_OUTPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_INTERNAL: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_initial_state(self) -> "InitialState":
        return self

    def to_simple(self) -> "InitialState":
        return self
