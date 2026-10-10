import struct

"""
Constants Definition
Precisely simulates IEC 61131-3 data types using bit-level calculations.
This ensures physical sandbox fidelity without rounding inaccuracies.
"""

# --- Integer Precision Helpers ---
def _u_max(bits: int) -> int:
    """Calculates exact 2^n - 1 without hardcoding."""
    return (1 << bits) - 1

def _s_min(bits: int) -> int:
    """Calculates exact -2^(n-1)."""
    return -(1 << (bits - 1))

def _s_max(bits: int) -> int:
    """Calculates exact 2^(n-1) - 1."""
    return (1 << (bits - 1)) - 1

# --- IEEE 754 Floating Point Precise Simulation ---
def _get_ieee754_max_float(is_double: bool = False) -> float:
    """
    Constructs the exact maximum finite value for IEEE 754 floats.
    REAL (32-bit): 0x7f7fffff (Sign=0, Exp=254, Mantissa=all 1s)
    LREAL (64-bit): 0x7fefffffffffffff (Sign=0, Exp=2046, Mantissa=all 1s)
    """
    if is_double:
        # LREAL: 8 bytes, Big-endian 'Q' (unsigned long long) to 'd' (double)
        # Max finite: Exponent is 2046 (0x7fe), Mantissa is all 1s
        return struct.unpack('>d', struct.pack('>Q', 0x7fefffffffffffff))[0]
    else:
        # REAL: 4 bytes, Big-endian 'I' (unsigned int) to 'f' (float)
        # Max finite: Exponent is 254 (0x7f7), Mantissa is all 1s
        return struct.unpack('>f', struct.pack('>I', 0x7f7fffff))[0]

# --- IEC 61131-3 Elementary Data Types Precise Limits ---
# All limits derived from bit-shifts or IEEE 754 bit-patterns.
REAL_MAX = _get_ieee754_max_float(is_double=False)
LREAL_MAX = _get_ieee754_max_float(is_double=True)

IEC_TYPE_LIMITS = {
    # 1. Bit Strings (Physical IO Masks)
    "BOOL":  {"min": 0, "max": 1, "type": int},  # 1 bit
    "BYTE":  {"min": 0, "max": _u_max(8),  "type": int},   # 8 bit
    "WORD":  {"min": 0, "max": _u_max(16), "type": int},   # 16 bit
    "DWORD": {"min": 0, "max": _u_max(32), "type": int},   # 32 bit
    "LWORD": {"min": 0, "max": _u_max(64), "type": int},   # 64 bit

    # 2. Signed Integers (Two's Complement)
    "SINT":  {"min": _s_min(8),  "max": _s_max(8),  "type": int},  # 1 byte
    "INT":   {"min": _s_min(16), "max": _s_max(16), "type": int},  # 2 byte
    "DINT":  {"min": _s_min(32), "max": _s_max(32), "type": int},  # 4 byte
    "LINT":  {"min": _s_min(64), "max": _s_max(64), "type": int},  # 8 byte

    # 3. Unsigned Integers
    "USINT": {"min": 0, "max": _u_max(8),  "type": int},   # 1 byte
    "UINT":  {"min": 0, "max": _u_max(16), "type": int},   # 2 byte
    "UDINT": {"min": 0, "max": _u_max(32), "type": int},   # 4 byte
    "ULINT": {"min": 0, "max": _u_max(64), "type": int},   # 8 byte

    # 4. IEEE 754 Floating Point (Calculated from Bit-Patterns)
    "REAL":  {"min": -REAL_MAX, "max": REAL_MAX, "type": float}, # 4 byte
    "LREAL": {"min": -LREAL_MAX, "max": LREAL_MAX, "type": float} # 8 byte
}

# --- LLM Experiment Constants ---
# Pricing based on 2026-03 usage data for RQ2 cost analysis.
# Here is an example.
MODEL_PRICING = {
    "deepseek-v3": {"input": 0.14, "output": 0.28}  # Cost per 1M tokens
}

# print(IEC_TYPE_LIMITS)  # For verification of constants during development