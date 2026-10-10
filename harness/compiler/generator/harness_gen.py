"""
Harness Generator - harness.c generator

Generate complete harness.c code based on POUInfo using Jinja2 template.
"""

import os
import sys
import copy
from pathlib import Path
from typing import Optional

# Safe import method
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader, Template

from harness.compiler.generator import POUInfo, VarDecl
from harness.compiler.generator.schema_gen import _BASIC_IEC_TYPES


class HarnessGenerator:
    """
harness.c generator

Generate harness.c code based on POUInfo, including:
- read_inputs function (input parsing + mapping)
- print_fb_state function (status output)
- main function (executed in a loop)
    """

    def __init__(self, template_dir: Optional[Path] = None):
        """
Initialize the generator

        Args:
template_dir: template directory, defaults to built-in template
        """
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Register custom filter
        self.env.filters['c_type'] = self._c_type_filter

    def generate(self, pou_info: POUInfo, template_name: str = "harness.c.j2") -> str:
        """
Generate harness.c code

        Args:
pou_info: POU information
template_name: template file name

        Returns:
# Generated C code string
        """
        template = self.env.get_template(template_name)

        # Prepare template variables (do not filter any type — MatIEC ensures c_type is correct)
        # intermediate = all variables except VAR_INPUT and VAR_OUTPUT
        # (VAR_IN_OUT, VAR, VAR_TEMP, VAR_STAT, VAR_GLOBAL, etc.)
        intermediate = [v for v in pou_info.all_vars if v not in pou_info.inputs and v not in pou_info.outputs]
        
        template_vars = {
            "pou_info": pou_info,
            "filtered_input_vars": pou_info.input_vars,
            "filtered_inputs": pou_info.inputs,
            "filtered_outputs": pou_info.outputs,
            "filtered_temps": pou_info.temps,
            "filtered_intermediate": intermediate,
            "c_var_prefix": "temp_",  # scanf local variable prefix
            "c_scalar_prefix": "int",  # Default scalar type (will be adjusted according to the actual type in the template)
        }

        return template.render(**template_vars)

    def generate_to_file(
        self,
        pou_info: POUInfo,
        output_path: Path,
        template_name: str = "harness.c.j2"
    ) -> bool:
        """
Generate harness.c and write to file

        Args:
pou_info: POU information
output_path: output file path
template_name: template file name

        Returns:
Whether successful
        """
        try:
            code = self.generate(pou_info, template_name)
            output_path.write_text(code, encoding="utf-8")
            return True
        except Exception as e:
            print(f"Error writing harness.c: {e}")
            return False

    @staticmethod
    def _c_type_filter(var: VarDecl) -> str:
        """Get the C type corresponding to the variable"""
        return var.c_type


# Built-in simplified template (used when template file does not exist)
FALLBACK_TEMPLATE = """/* Auto-generated Harness - Fallback Template */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "iec_types_all.h"
#include "POUS.h"

TIME __CURRENT_TIME;
BOOL __DEBUG = 0;
bool silent_mode = false;

void read_inputs({{ pou_info.pou_name_upper }}* instance) {
    /* TODO: Implement read_inputs */
}

void print_fb_state({{ pou_info.pou_name_upper }}* instance, int cycle) {
    if (silent_mode) return;
    printf("\\n--- Cycle %d ---\\n", cycle);
}

int main(int argc, char** argv) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--silent") == 0) silent_mode = true;
    }

    {{ pou_info.pou_name_upper }} instance;
    /* Zero the instance before init: matiec __SET_VAR skips writes when the
       FORCE flag byte holds garbage, silently skipping initialization. */
    memset(&instance, 0, sizeof({{ pou_info.pou_name_upper }}));
    {{ pou_info.pou_name_upper }}_init__(&instance, FALSE);

    int cycle = 0;
    while (1) {
        read_inputs(&instance);
        cycle++;

        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        __CURRENT_TIME.tv_sec = ts.tv_sec;
        __CURRENT_TIME.tv_nsec = ts.tv_nsec;

        {{ pou_info.pou_name_upper }}_body__(&instance);
        print_fb_state(&instance, cycle);
        fflush(stdout);
    }

    return 0;
}
"""
