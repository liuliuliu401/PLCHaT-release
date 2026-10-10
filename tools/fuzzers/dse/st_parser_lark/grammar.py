from __future__ import annotations

GRAMMAR = r"""
start: unit+

?unit: type_def | global_var_def | pou

// --- 1. Types & Global Definitions ---
type_def: "TYPE" type_block+ "END_TYPE"
type_block: NAME ":" "(" enum_list ")" ";"                                       -> type_enum
          | NAME ":" "STRUCT" (var_decl | at_overlay_decl)* "END_STRUCT" ";"     -> type_struct
enum_list: NAME ("," NAME)*

global_var_def: "VAR_GLOBAL" ["CONSTANT"] (var_decl | at_overlay_decl)* "END_VAR"

// --- 2. Program Organization Units (POU) ---
?pou: function_block | function | program

function_block: "FUNCTION_BLOCK" NAME decl_section* stmt* "END_FUNCTION_BLOCK"
function: "FUNCTION" NAME ":" type_name decl_section* stmt* "END_FUNCTION"
program: "PROGRAM" NAME decl_section* stmt* "END_PROGRAM"

// --- 3. Declarations ---
?decl_section: var_input | var_output | var_inout | var_temp | var_plain | var_constant

var_input: "VAR_INPUT" var_decl* "END_VAR"
var_output: "VAR_OUTPUT" var_decl* "END_VAR"
var_inout: "VAR_IN_OUT" var_decl* "END_VAR"
var_temp: "VAR_TEMP" var_decl* "END_VAR"
var_constant: "VAR" "CONSTANT" var_decl* "END_VAR"

var_plain: "VAR" (var_decl | at_overlay_decl)* "END_VAR"

var_decl: name_list ":" type_spec (":=" init_value)? ";"
name_list: NAME ("," NAME)*
init_value: expr | array_init
array_init: "[" expr ("," expr)* "]"

at_overlay_decl: NAME ":" type_spec "AT" overlay_target ";"
overlay_target: NAME | NAME "." INT

// --- 4. Type Specifications ---
?type_spec: type_name | enum_type | array_type | pointer_type
type_name: NAME                                            -> type_named
enum_type: "(" NAME ("," NAME)* ")"                        -> type_enum_inline
array_type: "ARRAY"i "[" array_range ("," array_range)* "]" "OF"i type_spec
array_range: expr ".." expr
pointer_type: "POINTER" "TO" type_spec                     -> type_pointer

// --- 5. Statements ---
?stmt: assign ";"                       -> stmt_assign
     | call ";"                         -> stmt_call
     | if_stmt
     | case_stmt
     | for_stmt
     | while_stmt
     | repeat_stmt
     | "EXIT" ";"                       -> stmt_exit
     | "CONTINUE" ";"                   -> stmt_continue
     | "RETURN" [expr] ";"              -> stmt_return

assign: lvalue ":=" expr
lvalue: (NAME | ABSNAME) index_suffix* ("." (NAME | INT) index_suffix*)*
index_suffix: "[" expr ("," expr)* "]"

call: NAME "(" [arg_list] ")"
arg_list: arg ("," arg)*
arg: NAME ":=" expr    -> arg_named
   | expr              -> arg_pos

if_stmt: "IF" expr "THEN" stmt* if_elsif_arm* if_else_arm? "END_IF" ";"
if_elsif_arm: "ELSIF" expr "THEN" stmt*
if_else_arm: "ELSE" stmt*

case_stmt: "CASE" expr "OF" case_arm+ ("ELSE" stmt*)? "END_CASE" ";"
case_arm: case_labels ":" stmt*
case_labels: case_label ("," case_label)*
case_label: case_value (".." case_value)?
case_value: INT | NAME

// FOR loops allow `FOR i:=1 TO 10` or expressions
for_stmt: "FOR" (NAME | NAME ":=" expr) "TO" expr ("BY" expr)? "DO" stmt* "END_FOR" ";"
while_stmt: "WHILE" expr "DO" stmt* "END_WHILE" ";"
repeat_stmt: "REPEAT" stmt* "UNTIL" expr "END_REPEAT" ";"

// --- 6. Expressions with precedence ---
?expr: or_expr
?or_expr: and_expr (OR_OP and_expr)*
?and_expr: rel_expr (AND_OP rel_expr)*
?rel_expr: add_expr (COMP_OP add_expr)*
?add_expr: mul_expr (ADD_OP mul_expr)*
?mul_expr: exp_expr (MUL_OP exp_expr)*
?exp_expr: unary (EXP_OP unary)*

OR_OP: "OR"i | "XOR"i | "OR_ELSE"i
AND_OP: "AND"i | "&" | "AND_THEN"i
COMP_OP: "<=" | ">=" | "<>" | "<" | ">" | "="
ADD_OP: "+" | "-"
MUL_OP: "*" | "/" | "MOD"i
EXP_OP: "**"
UNARY_OP: "NOT"i | "+" | "-"
?unary: UNARY_OP unary | primary

?primary: abs_ref
        | TIME_LIT        -> time_lit
        | TYPED_HEX_LIT   -> typed_hex_lit
        | BASE_LIT        -> base_lit
        | STRING_LIT      -> string_lit
        | BOOL_LIT        -> bool_lit
        | REAL            -> real_lit
        | INT             -> int_lit
        | ABSNAME         -> absname_ref
        | array_access    
        | member_access   
        | call            -> call_expr
        | NAME            -> var_ref
        | "(" expr ")"

array_access: NAME "[" expr ("," expr)* "]" ("." (NAME | INT))*
member_access: NAME ("." (NAME | INT))+

// --- 7. Terminals & Lexer rules ---
abs_ref: ABS_IO | ABS_DB

ABSNAME.10: /(I|Q|M)[0-9]+\.[0-9]+/
ABS_IO.10: /(I|Q|M)[0-9]+\.[0-9]+/
ABS_DB.10: /DB[0-9]+\.(DBX|DBB|DBW|DBD)[0-9]+(\.[0-9]+)?/

TIME_LIT.10: /(T#|TIME#)[0-9]+(\.[0-9]+)?(MS|ms|S|s|M|m|H|h|D|d)([0-9]+(\.[0-9]+)?(MS|ms|S|s|M|m|H|h|D|d))*/
TYPED_HEX_LIT.10: /(B#|W#|DW#)?16#[0-9A-Fa-f]+/
BASE_LIT.10: /(2#[01_]+|8#[0-7_]+|16#[0-9a-fA-F_]+)/

STRING_LIT: /'[^']*'/
BOOL_LIT: /(TRUE|FALSE)/i

NAME: /[A-Za-z_][A-Za-z0-9_]*/
REAL.5: /[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?/
INT: /[0-9]+/

%import common.WS
%ignore WS
%ignore /\(\*.*?\*\)/s
%ignore /\/\/[^\n]*/
"""





# from __future__ import annotations

# # Lark grammar for the IEC ST subset used by the test suite.

# GRAMMAR = r"""
# start: pou+

# ?pou: function_block | function | program

# function_block: "FUNCTION_BLOCK" NAME decl_section* stmt* "END_FUNCTION_BLOCK"
# function: "FUNCTION" NAME ":" type_name decl_section* stmt* "END_FUNCTION"
# program: "PROGRAM" NAME decl_section* stmt* "END_PROGRAM"

# // declarations
# ?decl_section: var_input | var_output | var_inout | var_temp | var_plain | var_constant

# var_input: "VAR_INPUT" var_decl* "END_VAR"
# var_output: "VAR_OUTPUT" var_decl* "END_VAR"
# var_inout: "VAR_IN_OUT" var_decl* "END_VAR"
# var_temp: "VAR_TEMP" var_decl* "END_VAR"
# var_constant: "VAR" "CONSTANT" var_decl* "END_VAR"

# var_plain: "VAR" (var_decl | at_overlay_decl)* "END_VAR"

# var_decl: NAME ":" type_spec (":=" expr)? ";"

# at_overlay_decl: NAME ":" type_spec "AT" overlay_target ";"
# overlay_target: NAME | NAME "." INT

# // Type specification: Can be named type or inline enumeration
# ?type_spec: type_name | enum_type
# type_name: NAME array_suffix?    -> type_named
# array_suffix: "[" INT ".." INT "]" "OF" type_spec
# enum_type: "(" NAME ("," NAME)* ")"

# // statements
# ?stmt: assign ";"                       -> stmt_assign
#      | call ";"                         -> stmt_call
#      | if_stmt
#      | case_stmt
#      | for_stmt
#      | while_stmt
#      | repeat_stmt
#      | "EXIT" ";"                       -> stmt_exit
#      | "CONTINUE" ";"                   -> stmt_continue
#      | "RETURN" ";"                     -> stmt_return

# assign: lvalue ":=" expr
# lvalue: (NAME | ABSNAME) index_suffix* ("." (NAME | INT) index_suffix*)*
# index_suffix: "[" expr "]"

# call: NAME "(" [arg_list] ")"
# arg_list: arg ("," arg)*
# arg: NAME ":=" expr    -> arg_named
#    | expr              -> arg_pos

# if_stmt: "IF" expr "THEN" stmt* if_elsif_arm* if_else_arm? "END_IF" ";"
# if_elsif_arm: "ELSIF" expr "THEN" stmt*
# if_else_arm: "ELSE" stmt*

# case_stmt: "CASE" expr "OF" case_arm+ ("ELSE" stmt*)? "END_CASE" ";"
# case_arm: case_labels ":" stmt*
# case_labels: case_label ("," case_label)*
# case_label: case_value (".." case_value)?
# case_value: INT | NAME

# for_stmt: "FOR" NAME ":=" expr "TO" expr ("BY" expr)? "DO" stmt* "END_FOR" ";"
# while_stmt: "WHILE" expr "DO" stmt* "END_WHILE" ";"
# repeat_stmt: "REPEAT" stmt* "UNTIL" expr "END_REPEAT" ";"

# // expressions with precedence
# ?expr: or_expr
# ?or_expr: and_expr (OR_OP and_expr)*
# ?and_expr: rel_expr (AND_OP rel_expr)*
# ?rel_expr: add_expr (COMP_OP add_expr)*
# ?add_expr: mul_expr (ADD_OP mul_expr)*
# ?mul_expr: unary (MUL_OP unary)*

# OR_OP: "OR"i | "XOR"i
# AND_OP: "AND"i | "&"
# COMP_OP: "<=" | ">=" | "<>" | "<" | ">" | "="
# ADD_OP: "+" | "-"
# MUL_OP: "*" | "/" | "MOD"i
# UNARY_OP: "NOT"i | "+" | "-"
# ?unary: UNARY_OP unary | primary

# ?primary: abs_ref
#         | TIME_LIT        -> time_lit
#         | TYPED_HEX_LIT   -> typed_hex_lit
#         | STRING_LIT      -> string_lit
#         | BOOL_LIT        -> bool_lit
#         | REAL            -> real_lit
#         | INT             -> int_lit
#         | ABSNAME         -> absname_ref
#         | array_access                    // Support arr[i] array index access
#         | member_access                   // Support Timer.Q and other member access
#         | call            -> call_expr
#         | NAME            -> var_ref
#         | "(" expr ")"

# // Array index access (e.g., VALVE_FAULT_HISTORY[i])
# array_access: NAME "[" expr "]"

# // Member access rule (e.g., HeartbeatTimer.Q)
# member_access: NAME ("." (NAME | INT))+

# // absolute lvalue tokens like Q0.0 / I0.0 / M0.0 used as lvalues
# ABSNAME.10: /(I|Q|M)[0-9]+\.[0-9]+/

# abs_ref: ABS_IO | ABS_DB

# // give abs tokens priority so I0.0 isn't tokenized as NAME('I0') DOT INT
# ABS_IO.10: /(I|Q|M)[0-9]+\.[0-9]+/
# ABS_DB.10: /DB[0-9]+\.(DBX|DBB|DBW|DBD)[0-9]+(\.[0-9]+)?/

# // literals and refs
# TIME_LIT.10: /(T#|TIME#)[0-9]+(\.[0-9]+)?(MS|ms|S|s|M|m|H|h|D|d)([0-9]+(\.[0-9]+)?(MS|ms|S|s|M|m|H|h|D|d))*/
# TYPED_HEX_LIT.10: /(B#|W#|DW#)?16#[0-9A-Fa-f]+/
# STRING_LIT: /'[^']*'/
# BOOL_LIT: /(TRUE|FALSE)/

# NAME: /[A-Za-z_][A-Za-z0-9_]*/
# REAL.5: /[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?/
# INT: /[0-9]+/

# %import common.WS
# %ignore WS
# %ignore /\(\*.*?\*\)/s
# %ignore /\/\/[^\n]*/
# """
