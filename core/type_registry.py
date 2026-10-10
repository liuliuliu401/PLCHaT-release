"""
Type Registry for Core Data Types
Provide unified type access and metadata management
"""

from typing import Dict, Type, Any, List
from core.data_types import (
    # Base types
    BaseType,
    TestStep,
    OracleViolation,
    AnalysisReport,
    InitialState,
    # Test case types
    IOPair, PLCTestCase, PLCVarState,
    # Execution types
    STExecutionResult,
    # Coverage types
    CoverageReport, CoverageData,
    # Plan types
    PlanPayload,
    # Evaluation types
    EvaluationReport,
    # IR types
    STVariableDecl, STPOUIR,
    # ST types
    StoredTestCase,
)


class TypeRegistry:
    """
    Type registry for all core data types.

    Provides methods to query types by name, check inheritance,
    and get metadata about registered types.
    """

    # Registry of all types
    _types: Dict[str, Type] = {}

    @classmethod
    def _initialize(cls):
        """Initialize the type registry with all core types."""
        if cls._types:
            return

        # Register all types
        cls._register_type("BaseType", BaseType)
        cls._register_type("TestStep", TestStep)
        cls._register_type("OracleViolation", OracleViolation)
        cls._register_type("InitialState", InitialState)
        cls._register_type("IOPair", IOPair)
        cls._register_type("PLCTestCase", PLCTestCase)
        cls._register_type("PLCVarState", PLCVarState)
        cls._register_type("STExecutionResult", STExecutionResult)
        cls._register_type("CoverageReport", CoverageReport)
        cls._register_type("CoverageData", CoverageData)
        cls._register_type("PlanPayload", PlanPayload)
        cls._register_type("EvaluationReport", EvaluationReport)
        cls._register_type("AnalysisReport", AnalysisReport)
        cls._register_type("STVariableDecl", STVariableDecl)
        cls._register_type("STPOUIR", STPOUIR)
        cls._register_type("StoredTestCase", StoredTestCase)

    @classmethod
    def _register_type(cls, name: str, type_class: Type):
        """Register a type in the registry."""
        cls._types[name] = type_class

    @classmethod
    def get_all_types(cls) -> Dict[str, Type]:
        """
        Return all registered types.

        Returns:
            Dictionary mapping type names to type classes
        """
        cls._initialize()
        return cls._types.copy()

    @classmethod
    def get_type_by_name(cls, name: str) -> Type:
        """
        Get a type by its name.

        Args:
            name: Name of the type

        Returns:
            The type class

        Raises:
            KeyError: If type is not registered
        """
        cls._initialize()
        if name not in cls._types:
            raise KeyError(f"Type '{name}' not found in registry. Available types: {list(cls._types.keys())}")
        return cls._types[name]

    @classmethod
    def is_base_type(cls, type_class: Type) -> bool:
        """
        Check if a type inherits from BaseType.

        Args:
            type_class: Type to check

        Returns:
            True if type inherits from BaseType
        """
        try:
            return issubclass(type_class, BaseType)
        except TypeError:
            return False

    @classmethod
    def get_base_type_subclasses(cls) -> List[Type]:
        """
        Get all types that inherit from BaseType.

        Returns:
            List of type classes that inherit from BaseType
        """
        cls._initialize()
        return [t for t in cls._types.values() if cls.is_base_type(t)]

    @classmethod
    def get_type_info(cls, type_class: Type) -> Dict[str, Any]:
        """
        Get metadata information about a type.

        Args:
            type_class: Type to query

        Returns:
            Dictionary with type metadata
        """
        import dataclasses
        import inspect

        info = {
            "name": type_class.__name__,
            "module": type_class.__module__,
            "is_dataclass": dataclasses.is_dataclass(type_class),
            "is_base_type": cls.is_base_type(type_class),
        }

        # Get dataclass fields if applicable
        if info["is_dataclass"]:
            info["fields"] = [
                {
                    "name": f.name,
                    "type": str(f.type),
                    "default": str(f.default) if f.default != dataclasses.MISSING else None,
                }
                for f in dataclasses.fields(type_class)
            ]

        # Get methods
        info["methods"] = [
            m for m in dir(type_class)
            if not m.startswith("_") and callable(getattr(type_class, m))
        ]

        return info


# Convenience functions
def get_all_types() -> Dict[str, Type]:
    """Convenience function to get all registered types."""
    return TypeRegistry.get_all_types()


def get_type_by_name(name: str) -> Type:
    """Convenience function to get a type by name."""
    return TypeRegistry.get_type_by_name(name)


def is_base_type(type_class: Type) -> bool:
    """Convenience function to check if type inherits from BaseType."""
    return TypeRegistry.is_base_type(type_class)


def get_base_type_subclasses() -> List[Type]:
    """Convenience function to get all BaseType subclasses."""
    return TypeRegistry.get_base_type_subclasses()
