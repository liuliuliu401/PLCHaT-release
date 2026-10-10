# Assertion Generation Fix Lessons

This document summarizes the issues and solutions found while fixing `harness_assertioned.c` files.

## Issue Classification

### 1. Format String Line Breaks (High Priority)

**Problem**:
In LLM-generated `fprintf` statements, the format string breaks across lines, causing C compile errors.

**Example broken code**:
```c
fprintf(stderr, "SECURITY ASSERT: channel_retval overflow int16 for ch %d
", ch+1);
exit(1);
```

**Compile error**:
```
error: missing terminating " character
```

**Root cause**:
- When the LLM generates code, long strings may be wrapped automatically
- The wrapped string does not use string concatenation syntax (`\` or `" "...""`)

**Solution**:
1. Add a `_fix_assertion_code` method in `patch_inserter.py`
2. Detect unclosed quotes with a regular expression
3. Merge the wrapped format strings

**Implementation**:
```python
def _fix_assertion_code(self, code: str) -> str:
    """Fix line breaks inside format strings in assertion code."""
    lines = code.split('\n')
    result = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if 'fprintf(' in line:
            # Check for an odd number of quotes (unclosed format string)
            if line.count('"') % 2 == 1:
                # Search forward for the closing quote
                merged = line
                j = i + 1
                while j < len(lines):
                    merged += ' ' + lines[j].lstrip()
                    if merged.count('"') % 2 == 0:
                        break
                    j += 1
                result.append(merged)
                i = j
            else:
                result.append(line)
        else:
            result.append(line)

        i += 1

    return '\n'.join(result)
```

### 2. Undefined Variables (High Priority)

**Problem**:
The generated assertion code uses undefined variables.

**Example broken code**:
```c
if (instance.CHANNEL_ENABLE.value.table[ch] < 0 || instance.CHANNEL_ENABLE.value.table[ch] > 1) {
    fprintf(stderr, "SECURITY ASSERT: channel_enable out of boolean range [0,1] for ch %d\n", ch+1);
    exit(1);
}
```

**Problem**:
- The variable `ch` is not defined
- A loop should iterate over the array, or fixed indices should be used

**Solution**:
Add a loop definition in the assertion code, or check each array element individually.

**Fix example**:
```c
// Option 1: use a loop
for (int ch = 0; ch < 10; ch++) {
    if (instance.CHANNEL_ENABLE.value.table[ch] < 0 || instance.CHANNEL_ENABLE.value.table[ch] > 1) {
        fprintf(stderr, "SECURITY ASSERT: channel_enable out of boolean range [0,1] for ch %d\n", ch+1);
        exit(1);
    }
}

// Option 2: use a helper function (recommended)
int check_assertions(FB_TRAFFICLIGHT* instance) {
    // Assertion 1: ...
    if (condition) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: ...\n");
        fflush(stderr);
        return 1;
    }
    return 0;
}
```

### 3. Struct Access (Medium Priority)

**Problem**:
Assertion code uses the wrong member access style.

**Scenario analysis**:
- In `read_inputs` and `print_fb_state`, use `instance->` (the parameter is a pointer)
- In assertion checks in `main`, pass the pointer as `&instance`
- So assertion code should use `instance->`, not `instance.`

**Wrong example**:
```c
if (instance.LAMP_NS_GREEN.value && instance.LAMP_NS_RED.value) {
    // Wrong: instance is not a pointer
}
```

**Correct example**:
```c
if (instance->LAMP_NS_GREEN.value && instance->LAMP_NS_RED.value) {
    // Correct: instance is a pointer
}
```

**Solution**:
1. Explicitly require `instance->` member access in the LLM prompt
2. Check the member access style in the code validation step

### 4. Array Access Bounds (Medium Priority)

**Problem**:
Assertion code accesses array elements without bounds checks.

**Example**:
```c
if (instance.CHANNEL_ENABLE.value.table[ch] < 0) {
    // If ch is not properly initialized or checked, this may go out of bounds
}
```

**Solution**:
1. Ensure loop variables stay within the valid range
2. Define array sizes with constants
3. Add bounds checks

## Recommended Assertion Code Templates

### Template 1: Simple Assertion Check

```c
/* Assertion checking function - returns assertion type or 0 if no assertion failed */
int check_assertions(POU_NAME* instance) {
    /* Assertion 1: <description> */
    if (condition) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: <DESCRIPTION>\n");
        fflush(stderr);
        return 1;
    }

    /* Assertion 2: <description> */
    if (condition) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: <DESCRIPTION>_<VALUE>\n",
                (long)instance->VAR.value);
        fflush(stderr);
        return 2;
    }

    return 0;  /* No assertion failed */
}
```

### Template 2: Array Element Check

```c
/* Assertion checking function with array iteration */
int check_assertions(POU_NAME* instance) {
    #define ARRAY_SIZE 10

    for (int i = 0; i < ARRAY_SIZE; i++) {
        /* Assertion: <description> */
        if (instance->ARRAY.value.table[i] < min_value ||
            instance->ARRAY.value.table[i] > max_value) {
            fprintf(stderr, "SECURITY_ASSERTION_FAILED: <DESCRIPTION>_INDEX_%d_VALUE_%ld\n",
                    i, (long)instance->ARRAY.value.table[i]);
            fflush(stderr);
            return 1;
        }
    }

    return 0;
}
```

### Template 3: main Function Integration

```c
int main(int argc, char** argv) {
    /* ... initialization code ... */

    POU_NAME instance;
    POU_NAME_init__(&instance, FALSE);

    int cycle = 0;
    while (1) {
        read_inputs(&instance);
        cycle++;

        /* Time update */
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        __CURRENT_TIME.tv_sec = ts.tv_sec;
        __CURRENT_TIME.tv_nsec = ts.tv_nsec;

        /* Execute program logic */
        POU_NAME_body__(&instance);

        /* Check assertions after execution */
        int assertion_failed = check_assertions(&instance);
        if (assertion_failed != 0) {
            /* Print state before exiting */
            print_fb_state(&instance, cycle);
            fflush(stdout);
            exit(assertion_failed);  /* Exit with assertion code */
        }

        print_fb_state(&instance, cycle);
        fflush(stdout);
    }

    return 0;
}
```

## LLM Prompt Improvement Suggestions

### Current Problem Prompt

Add the following to `ASSERTION_DESIGN_PROMPT_V4` in `llm_assertion_designer_v4.py`:

```
## Code Generation Requirements (Important)

1. **Variable access rules** (must follow):
   - Use `instance->VAR.value` to access simple variables
   - Use `instance->ARRAY.value.table[index]` to access array elements
   - **Never** use undefined variables (e.g., `ch`, `i`); define them first

2. **Format string rules**:
   - Format strings must stay on one line
   - Long strings may use concatenation: `"string1 " "string2"`
   - **Never** break a format string across lines

3. **Array check rules**:
   - When iterating an array, define the loop variable first
   - Define array sizes with `#define` or constants
   - Loop bounds must be explicit

4. **Output format requirements**:
   - Use `fprintf(stderr, "SECURITY_ASSERTION_FAILED: <description>\n", args);`
   - Call `fflush(stderr);` to ensure output
   - Return an assertion type code (non-zero means failure)

5. **Code structure**:
   - A standalone `check_assertions()` function is recommended
   - Return 0 for no assertion failed, non-zero for a specific assertion failure
```

## Validation Checklist

After generating assertion code, the following checks should be run:

- [ ] All format strings are on one line (or properly concatenated)
- [ ] All used variables are defined
- [ ] `instance->` is used instead of `instance.`
- [ ] Array access uses `.table[index]`
- [ ] Loop bounds are explicit and safe
- [ ] `fflush(stderr)` is called
- [ ] Error messages clearly describe the failure reason

## Test Cases

### Case 1: StackMin - Stack Overflow Detection

**Assertion goal**: detect the stack pointer exceeding capacity

**Correct code**:
```c
int check_assertions(STACKMIN* instance) {
    int stack_ptr = calculate_stack_ptr(instance);

    if (instance->POP.value && stack_ptr == 0) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: STACK_UNDERFLOW\n");
        fflush(stderr);
        return 1;
    }

    if (instance->PUSH.value && stack_ptr >= STACK_SIZE) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: STACK_OVERFLOW\n");
        fflush(stderr);
        return 2;
    }

    return 0;
}
```

### Case 2: TrafficLight - Signal Conflict Detection

**Assertion goal**: detect green and red lights active at the same time in the same direction

**Correct code**:
```c
int check_assertions(FB_TRAFFICLIGHT* instance) {
    if (instance->LAMP_NS_GREEN.value && instance->LAMP_NS_RED.value) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: NS_GREEN_AND_RED_ACTIVE\n");
        fflush(stderr);
        return 1;
    }

    if (instance->LAMP_EW_GREEN.value && instance->LAMP_EW_RED.value) {
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: EW_GREEN_AND_RED_ACTIVE\n");
        fflush(stderr);
        return 2;
    }

    return 0;
}
```

## Next Improvements

1. **Stronger code validation**: add stricter syntax checks to `_validate_code` in `llm_assertion_designer_v4.py`
2. **Templated generation**: provide predefined templates for common assertion patterns
3. **Compile validation**: automatically try compiling after generation and capture compile errors
4. **Iterative repair**: on compile failure, feed the error back to the LLM for repair
