"""
Assertion Patcher - inserts LLM-generated C assertion code into harness.c

Handles both function-style (check_assertions) and block-style assertions.
Comprehensive post-processing fixes common LLM output issues:
  - Multiline/split fprintf format strings
  - Real newlines inside C string literals
  - instance.VAR vs inst->VAR access pattern normalization
  - Undeclared loop variables
  - Brace mismatches
"""

from pathlib import Path
from dataclasses import dataclass
import re
import logging
import textwrap

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from harness.test_analysis.assertion.llm_assertion_designer import AssertionCode


@dataclass
class PatchResult:
    success: bool
    original_path: Path
    patched_path: Path
    error: str = ""


class AssertionPatcher:

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)

    # ==================================================================
    # Public
    # ==================================================================

    def insert_assertions(
        self, harness_path: Path, assertion_code: AssertionCode,
        pou_name_upper: str, output_dir: Path = None, pous_h_path: Path = None
    ) -> PatchResult:
        """
        Insert assertion code into harness.c.

        Args:
            harness_path: Original harness path
            assertion_code: Generated assertion code
            pou_name_upper: POU name (e.g., "STACKMIN")
            output_dir: Where to write patched harness (defaults to harness_path.parent)
            pous_h_path: Explicit path to POUS.h (enables member-aware post-processing;
                if omitted, common locations near harness/output dir are searched)
        """
        try:
            self.logger.info(f"Reading harness: {harness_path}")
            harness_content = harness_path.read_text(encoding='utf-8')

            raw_code = assertion_code.c_code
            members = self._parse_pou_struct(harness_path, pou_name_upper,
                                             output_dir, pous_h_path)
            fixed_code = self._fix_assertion_code(raw_code, pou_name_upper, members)

            # Detect: standalone function or raw code block
            is_function = 'check_assertions' in fixed_code and 'return 0' in fixed_code

            if is_function:
                patched_content = self._insert_function_style(
                    harness_content, fixed_code, pou_name_upper)
            else:
                patched_content = self._insert_block_style(
                    harness_content, fixed_code, pou_name_upper)

            # Determine output directory
            output_path = output_dir if output_dir else harness_path.parent
            patched_path = output_path / f"{harness_path.stem}_assertioned.c"
            patched_path.write_text(patched_content, encoding='utf-8')
            self.logger.info(f"Assertions inserted: {patched_path}")

            return PatchResult(success=True, original_path=harness_path,
                               patched_path=patched_path)

        except Exception as e:
            self.logger.error(f"Assertion insertion failed: {e}")
            return PatchResult(success=False, original_path=harness_path,
                               patched_path=harness_path, error=str(e))

    def remove_assertions(self, patched_path: Path) -> Path:
        original = patched_path.parent / patched_path.stem.replace("_assertioned", ".c")
        if not original.exists():
            return patched_path
        return original

    # ==================================================================
    # Insertion strategies
    # ==================================================================

    def _insert_function_style(self, content: str, code: str, pou_name: str) -> str:
        main_idx = content.find('\nint main(') or content.find('\nvoid main(')
        if main_idx == -1:
            raise ValueError("Cannot find main() in harness")
        before = content[:main_idx]
        after = content[main_idx:]

        body_call = f'{pou_name}_body__(&instance);'
        body_idx = after.find(body_call)
        if body_idx == -1:
            raise ValueError(f"Cannot find {body_call} in main()")

        insert_pos = body_idx + len(body_call)
        call_code = (
            '\n    int assertion_result = check_assertions(&instance);'
            '\n    if (assertion_result != 0) { fprintf(stderr, "ASSERTION_RESULT=%d ASSERTION_CYCLE=%d\\n", assertion_result, cycle); fflush(stderr); }'
        )
        return before + '\n' + code + '\n' + after[:insert_pos] + call_code + after[insert_pos:]

    def _insert_block_style(self, content: str, code: str, pou_name: str) -> str:
        body_call = f'{pou_name}_body__(&instance);'
        idx = content.find(body_call)
        if idx == -1:
            raise ValueError(f"Cannot find {body_call} in harness")
        insert_pos = idx + len(body_call)
        while insert_pos < len(content) and content[insert_pos] in ' \t':
            insert_pos += 1
        nl = '\n' if insert_pos < len(content) and content[insert_pos] != '\n' else ''
        return content[:insert_pos] + nl + '\n' + code + '\n' + content[insert_pos:]

    # ==================================================================
    # LLM output post-processing
    # ==================================================================

    def _fix_assertion_code(self, code: str, pou_name_upper: str = None,
                            members: dict = None) -> str:
        """Comprehensive post-processing of LLM-generated assertion code.

        Handles all known LLM output patterns — no prompt can guarantee correctness.

        Args:
            code: Raw LLM-generated C code
            pou_name_upper: POU name (e.g., "STACKMIN") to replace POU_NAME placeholder
            members: {MEMBER_UPPER: ('value'|'fb', c_type_upper)} parsed from POUS.h

        Returns:
            Fixed C code ready for insertion
        """
        if not code or not code.strip():
            return code

        members = members or {}

        # ---- Step 1: Strip markdown fences and extract C code ----
        code = self._strip_markdown(code)

        # ---- Step 1b: Translate IEC/ST numeric literals (16#FF, 2#1010, ...) to C ----
        code = self._fix_iec_literals(code)

        # ---- Step 2: Replace POU_NAME placeholder with actual POU name ----
        if pou_name_upper:
            code = code.replace('POU_NAME', pou_name_upper)
            self.logger.info(f"Replaced POU_NAME with {pou_name_upper}")

        # ---- Step 2b: Force the check_assertions() parameter type to the real
        # MatIEC struct typedef. Weak LLMs emit the ST-source name (e.g.
        # `FB_MergeBytes` / `StringToTaddr`) -> "unknown type name". ----
        if pou_name_upper:
            code = self._fix_struct_type_name(code, pou_name_upper)

        # ---- Step 3: Merge split fprintf format strings ----
        code = self._merge_split_fprintf(code)

        # ---- Step 4: Escape real newlines inside C string literals ----
        code = self._escape_newlines_in_strings(code)

        # ---- Step 5: Normalize variable access (instance.VAR → instance->VAR) ----
        # In the code block inserted after body__() in main(), 'instance' is a
        # struct value, so dot notation (instance.VAR.value) is CORRECT.
        # But LLMs often output arrow notation (instance->VAR.value) or inst->.
        # Make consistent: keep dot notation for main() context.
        code = self._normalize_instance_access(code)

        # ---- Step 5a: Uppercase member names to match MatIEC C struct fields.
        # Weak LLMs keep ST-source casing (inst->opeMode) -> "no member named". ----
        if members:
            code = self._fix_member_case(code, members)

        # ---- Step 5b: Append missing `.value` (LLM often writes inst->VAR instead of
        # inst->VAR.value; the bare struct can't be compared to a scalar -> compile error).
        # FB-typed members (TON, etc.) have no `.value`, so they are excluded. ----
        fb_members = {m for m, (kind, _) in members.items() if kind == 'fb'}
        code = self._fix_missing_value(code, fb_members)

        # ---- Step 5c: Drop individual assertion statements that reference members
        # we cannot safely compile (FB instances, hallucinated/nested-lowercase names).
        # Keeping the remaining valid assertions recovers a compilable harness. ----
        if members:
            code = self._drop_bad_assertions(code, members)

        # ---- Step 6: Add missing variable declarations for loops ----
        code = self._add_loop_declarations(code)

        # ---- Step 7: Fix common C syntax issues ----
        code = self._fix_syntax(code)

        return code

    # ---- sub-steps ----

    @staticmethod
    def _fix_iec_literals(code: str) -> str:
        """Convert IEC 61131-3 based-number literals (copied from ST source) to valid C.
        e.g. 16#0000 -> 0x0, 16#8A04 -> 0x8a04, 2#1010 -> 10, 8#777 -> 511, 10#42 -> 42.
        Without this, LLM assertions that reference status codes like `16#0000` fail to compile."""
        def repl(m):
            base = int(m.group(1)); digits = m.group(2).replace('_', '')
            try:
                val = int(digits, base)
            except ValueError:
                return m.group(0)
            return hex(val) if base == 16 else str(val)
        return re.sub(r'\b(\d{1,2})#([0-9A-Fa-f_]+)', repl, code)

    # ---- POUS.h struct parsing & member-aware fixes ----

    def _parse_pou_struct(self, harness_path: Path, pou_name_upper: str,
                          output_dir: Path = None, pous_h_path: Path = None) -> dict:
        """Parse the MatIEC-generated POU struct from POUS.h.

        Returns {MEMBER_UPPER: (kind, c_type_upper)} where kind is:
          - 'value' for scalar/array/string members (accessed via `.value`)
          - 'fb'    for nested function-block instances (TON, ..., no `.value`)
        Empty dict if POUS.h cannot be located/parsed (fixes then degrade gracefully)."""
        candidates = []
        if pous_h_path:
            candidates.append(Path(pous_h_path))
        # Search the harness dir, the output dir, and their common build subdirs.
        roots = []
        if harness_path:
            roots.append(harness_path.parent)
        if output_dir:
            roots.append(Path(output_dir))
        for root in roots:
            candidates.append(root / "POUS.h")
            candidates.append(root / "temp_compile" / "POUS.h")
            candidates.append(root / "assertion_build" / "POUS.h")
        pous_h = next((p for p in candidates if p and p.exists()), None)
        if not pous_h:
            self.logger.info("POUS.h not found; member-aware fixes disabled")
            return {}
        try:
            text = pous_h.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return {}

        structs = {
            name: body
            for body, name in re.findall(
                r'typedef\s+struct\s*\{(.*?)\}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;',
                text, re.S)
        }
        body = None
        if pou_name_upper and pou_name_upper in structs:
            body = structs[pou_name_upper]
        elif structs:
            body = list(structs.values())[-1]
        if body is None:
            return {}

        members = {}
        for dm in re.finditer(
                r'__DECLARE_VAR\s*\(\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*\)', body):
            members[dm.group(2).upper()] = ('value', dm.group(1).upper())
        for fm in re.finditer(
                r'^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*;',
                body, re.M):
            name = fm.group(2).upper()
            if name not in members:
                members[name] = ('fb', fm.group(1).upper())
        if members:
            self.logger.info(
                f"Parsed {len(members)} POU members from POUS.h "
                f"({sum(1 for k,_ in members.values() if k=='fb')} FB)")
        return members

    @staticmethod
    def _fix_struct_type_name(code: str, pou_name_upper: str) -> str:
        """Force the check_assertions() parameter type to the real struct typedef.
        Weak LLMs emit the ST-source name (FB_MergeBytes / StringToTaddr) -> compile error."""
        return re.sub(
            r'(check_assertions\s*\(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*\*)',
            lambda m: m.group(1) + pou_name_upper + m.group(3), code)

    @staticmethod
    def _fix_member_case(code: str, members: dict) -> str:
        """Uppercase the top-level member name after inst->/instance->/instance. so it
        matches the MatIEC C struct field (which is always uppercase)."""
        def repl(m):
            ident = m.group(2)
            if ident.upper() in members and ident != ident.upper():
                return m.group(1) + ident.upper()
            return m.group(0)
        return re.sub(r'((?:inst->|instance->|instance\.))([A-Za-z_][A-Za-z0-9_]*)',
                      repl, code)

    def _drop_bad_assertions(self, code: str, members: dict) -> str:
        """Remove top-level statements that reference constructs we cannot safely
        compile, keeping the remaining valid assertions:
          - FB-instance members (TON, ... — have no scalar fields the LLM expects)
          - member names not present in the struct (hallucinated)
          - nested lowercase sub-fields (inst->X.fooBar — wrong nested access)
        """
        fb_members = {m for m, (kind, _) in members.items() if kind == 'fb'}

        head, body, tail = self._split_function_body(code)
        if body is None:
            head, body, tail = '', code, ''

        units = self._split_top_level(body)
        kept = []
        dropped = 0
        for unit in units:
            if self._unit_is_bad(unit, members, fb_members):
                dropped += 1
                continue
            kept.append(unit)
        if dropped:
            self.logger.info(f"Dropped {dropped} unfixable assertion statement(s)")
        return head + ''.join(kept) + tail

    @staticmethod
    def _unit_is_bad(unit: str, members: dict, fb_members: set) -> bool:
        stripped = unit.strip()
        if not stripped:
            return False
        # Never drop the terminal `return 0;`
        if re.fullmatch(r'return\s+0\s*;', stripped):
            return False
        # Strip string literals and comments so prose/format-text is never matched
        no_str = re.sub(r'"[^"]*"', '""', unit)
        no_str = re.sub(r'/\*.*?\*/', ' ', no_str, flags=re.S)
        no_str = re.sub(r'//[^\n]*', ' ', no_str)
        # 1) references an FB instance member or a name not in the struct (hallucinated)
        for m in re.finditer(r'(?:inst->|instance->|instance\.)([A-Za-z_][A-Za-z0-9_]*)', no_str):
            ident = m.group(1).upper()
            if ident in fb_members:
                return True
            if ident not in members:
                return True
        # 2) nested lowercase sub-field after a known member (wrong nested access)
        if re.search(r'(?:inst->|instance->|instance\.)[A-Za-z0-9_]+\.(?!value\b|table\b)[a-z]', no_str):
            return True
        # 3) leaked ST-style infix operators (illegal in C: `x AND y`, `a OR b`, ...)
        if re.search(r'\s(?:AND|OR|XOR|MOD)\s', no_str):
            return True
        return False

    @staticmethod
    def _split_function_body(code: str):
        """Split `... check_assertions(...) { <body> } ...` into (head, body, tail).
        Returns (None, None, None) markers via (head='', body=None) if not found."""
        idx = code.find('check_assertions')
        if idx == -1:
            return '', None, ''
        brace = code.find('{', idx)
        if brace == -1:
            return '', None, ''
        depth = 0
        i = brace
        while i < len(code):
            if code[i] == '{':
                depth += 1
            elif code[i] == '}':
                depth -= 1
                if depth == 0:
                    return code[:brace + 1], code[brace + 1:i], code[i:]
            i += 1
        return '', None, ''

    @staticmethod
    def _split_top_level(body: str) -> list:
        """Split a C block body into top-level statements/blocks, keeping if/else
        chains together. Whitespace/comments attach to the following unit."""
        units = []
        buf = ''
        depth = 0
        paren = 0
        n = len(body)
        i = 0
        while i < n:
            ch = body[i]
            buf += ch
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    j = i + 1
                    while j < n and body[j] in ' \t\r\n':
                        j += 1
                    if body[j:j + 4] == 'else':
                        i += 1
                        continue
                    units.append(buf)
                    buf = ''
            elif ch == '(':
                paren += 1
            elif ch == ')':
                paren -= 1
            elif ch == ';' and depth == 0 and paren == 0:
                units.append(buf)
                buf = ''
            i += 1
        if buf.strip():
            units.append(buf)
        return units

    @staticmethod
    def _strip_markdown(code: str) -> str:
        for fence in ('```c', '```C', '```'):
            if fence in code:
                start = code.find(fence) + len(fence)
                end = code.rfind('```')
                if end > start:
                    code = code[start:end]
                break
        return code.strip()

    @staticmethod
    def _merge_split_fprintf(code: str) -> str:
        """Merge fprintf format strings that LLM split across physical lines."""
        lines = code.split('\n')
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if 'fprintf(' in line and line.count('"') % 2 == 1:
                merged = line
                j = i + 1
                while j < len(lines):
                    candidate = lines[j].lstrip()
                    # Stop if this line starts a new statement/comment/closing brace
                    if (candidate.startswith('//') or candidate.startswith('/*') or
                        candidate.startswith('}') or candidate.startswith('if ') or
                        candidate.startswith('int ') or candidate.startswith('for ') or
                        candidate.startswith('return') or candidate.startswith('exit')):
                        break
                    merged += ' ' + candidate
                    if merged.count('"') % 2 == 0:
                        j += 1
                        break
                    j += 1
                result.append(merged)
                i = j
            else:
                result.append(line)
            i += 1
        return '\n'.join(result)

    @staticmethod
    def _escape_newlines_in_strings(code: str) -> str:
        """Replace real newlines inside C string literals with escaped \\n."""
        def _fix(m):
            s = m.group(0)
            if '\n' in s:
                return s.replace('\n', '\\n')
            return s
        return re.sub(r'"[^"]*"', _fix, code)

    @staticmethod
    def _normalize_instance_access(code: str) -> str:
        """Keep dot notation for main() context: instance->VAR → instance.VAR."""
        return re.sub(r'\binstance->([A-Z_][A-Z0-9_]*)\.value',
                      r'instance.\1.value', code)

    @staticmethod
    def _fix_missing_value(code: str, fb_members: set = None) -> str:
        """Append missing `.value` to scalar variable access.
        MatIEC variables are structs with a `.value` field; LLMs often write
        `inst->INPUTNUMBER` instead of `inst->INPUTNUMBER.value`, which makes the bare
        struct get compared to a scalar -> compile error. Only scalars are fixed:
        access already ending in `.value`/`.value.table`/`.` or followed by `[` (array)
        is left untouched. FB-typed members (TON, etc.) have no `.value` and are skipped."""
        fb_members = fb_members or set()

        def repl(m):
            name = m.group(2)
            if name.upper() in fb_members:
                return m.group(0)
            return f'{m.group(1)}{name}.value'

        return re.sub(r'((?:inst->|instance->|instance\.))([A-Z_][A-Z0-9_]*)(?![A-Za-z0-9_.\[])',
                      repl, code)

    @staticmethod
    def _add_loop_declarations(code: str) -> str:
        """Add missing 'int' declarations for common loop variables."""
        table_vars = set(re.findall(r'table\[(\w+)\]', code))
        need_decl = []
        for v in table_vars:
            if v in ('0','1','2','3','4','5','6','7','8','9'):
                continue
            if not re.search(rf'\bint\s+{v}\b', code):
                need_decl.append(v)

        if need_decl:
            preamble = '\n'.join(f'    int {v} = 0;  /* auto-declared */' for v in need_decl)
            # Insert near the beginning, after any #define lines
            lines = code.split('\n')
            insert_at = 0
            for i, line in enumerate(lines):
                if not line.strip().startswith('#') and not line.strip().startswith('//') and line.strip():
                    insert_at = i
                    break
            lines.insert(insert_at, preamble)
            code = '\n'.join(lines)
        return code

    @staticmethod
    def _fix_syntax(code: str) -> str:
        """Fix common C syntax errors in LLM output."""
        # Fix: double-semicolons
        code = code.replace(';;', ';')
        # Fix: stray backslash-newline escapes
        code = re.sub(r'\\\n\s*', '', code)
        # Fix: missing semicolons before closing braces
        code = re.sub(r'(\S)\n(\s*})', r'\1;\n\2', code)
        return code


__all__ = ["AssertionPatcher", "PatchResult"]
