# src/extract_python.py
from pathlib import Path
from typing import Dict, Any, List, Optional
import os

from .ast_utils import (
    find_child_by_field_name, get_node_text,
    get_docstring_from_python_node, is_node_type, run_query, LANG_CONFIG # Added LANG_CONFIG
)


LANG = "python"

def _build_python_fqn(file_rel_path: str, item_name: str, parent_fqn: Optional[str] = None) -> str:
    """Builds a Python FQN."""
    # Convert file path to module path
    module_parts = file_rel_path.replace(os.sep, '.').split('.')
    if module_parts[-1] == "py": # from .py extension
        module_parts.pop()
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop() # remove __init__
    
    base_module_path = ".".join(filter(None, module_parts))

    if parent_fqn:
        # If item_name is already fully qualified due to recursion, don't prepend parent_fqn's base
        # This check is simplistic; assumes item_name won't naturally contain parent_fqn base.
        if base_module_path and parent_fqn.startswith(base_module_path):
             # Parent FQN already includes the module path, just append item name if not already there
             if not parent_fqn.endswith(item_name): # Avoid double-adding if name is part of parent_fqn in some cases
                 return f"{parent_fqn}.{item_name}"
             return parent_fqn
        else: # Parent FQN is from a different module context or no base_module_path (e.g. library root)
             return f"{parent_fqn}.{item_name}"

    # If no parent_fqn, construct from module path and item name
    if base_module_path:
        return f"{base_module_path}.{item_name}"
    return item_name


def extract_py_signature(func_node, content_bytes: bytes) -> Dict[str, Any]:
    sig: Dict[str, Any] = {"params": [], "return_type": "unknown", "async": False}
    
    # Check for async (usually the first child if present)
    # tree-sitter python grammar: (function_definition "async" ... )
    is_async_node = func_node.child_by_field_name("async") # Check for async keyword by field name if grammar supports
    if not is_async_node and func_node.children and func_node.children[0].type == 'async': # Fallback for older/different grammar
         is_async_node = func_node.children[0]
    if is_async_node:
        sig["async"] = True

    param_list_node = find_child_by_field_name(func_node, "parameters")
    if param_list_node:
        for child in param_list_node.named_children: 
            param_info = {"name": "_unknown_", "type": "unknown", "default_value": None}
            if child.type == 'identifier': 
                param_info["name"] = get_node_text(child, content_bytes)
            elif child.type == 'typed_parameter': 
                name_node = child.child_by_field_name("name") # Python grammar uses 'name' for identifier in typed_parameter
                if not name_node and child.children: # Fallback if 'name' field not present
                    name_node = child.children[0] if child.children[0].type == 'identifier' else None

                type_node = child.child_by_field_name("type")
                param_info["name"] = get_node_text(name_node, content_bytes) if name_node else "_anon_"
                param_info["type"] = get_node_text(type_node, content_bytes) if type_node else "unknown"
            elif child.type == 'default_parameter': 
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                value_node = child.child_by_field_name("value")
                param_info["name"] = get_node_text(name_node, content_bytes) if name_node else "_anon_"
                param_info["type"] = get_node_text(type_node, content_bytes) if type_node else "unknown"
                param_info["default_value"] = get_node_text(value_node, content_bytes)
            elif child.type == 'list_splat_pattern' or child.type == 'tuple_pattern': # *args / * 
                name_node = child.named_child(0) if child.named_child_count > 0 else None
                param_info["name"] = f"*{get_node_text(name_node, content_bytes)}" if name_node and name_node.type == 'identifier' else "*args"
                param_info["type"] = "tuple" 
            elif child.type == 'dictionary_splat_pattern': # **kwargs
                name_node = child.named_child(0) if child.named_child_count > 0 else None
                param_info["name"] = f"**{get_node_text(name_node, content_bytes)}" if name_node and name_node.type == 'identifier' else "**kwargs"
                param_info["type"] = "dict" 
            elif child.type == '*':
                param_info["name"] = "*"
                param_info["type"] = "_marker_args_" # Keyword-only argument marker
            elif child.type == '/':
                param_info["name"] = "/"
                param_info["type"] = "_marker_pos_only_" # Positional-only argument marker

            if param_info["name"] != "_unknown_":
                sig["params"].append(param_info)

    return_type_node = find_child_by_field_name(func_node, "return_type")
    if return_type_node: # This node is the actual type node
        sig["return_type"] = get_node_text(return_type_node, content_bytes) or "unknown"
    
    return sig

def extract_py_function_details(func_node, file_path: Path, repo_root: Path, content_bytes: bytes, parent_fqn: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rel_path_str = str(file_path.relative_to(repo_root))
    name_node = find_child_by_field_name(func_node, "name")
    func_name = get_node_text(name_node, content_bytes)
    if not func_name: return None

    qualified_name = _build_python_fqn(rel_path_str, func_name, parent_fqn)
    signature = extract_py_signature(func_node, content_bytes)
    source_code = get_node_text(func_node, content_bytes)
    body_node = find_child_by_field_name(func_node, "body")
    docstring = get_docstring_from_python_node(body_node, content_bytes) if body_node else None

    return {
        "name": func_name, "qualified_name": qualified_name,
        "source_file": rel_path_str, "language": LANG,
        "line_start": func_node.start_point[0] + 1, "line_end": func_node.end_point[0] + 1,
        "signature": signature, "docstring": docstring, "source_code": source_code,
        "logic_ops": [], "dependencies": [], "test_specs_covering": []
    }

def extract_py_data_structure(class_node, file_path: Path, repo_root: Path, content_bytes: bytes, parent_fqn: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rel_path_str = str(file_path.relative_to(repo_root))
    name_node = find_child_by_field_name(class_node, "name")
    class_name = get_node_text(name_node, content_bytes)
    if not class_name: return None

    qualified_name = _build_python_fqn(rel_path_str, class_name, parent_fqn)
    source_code = get_node_text(class_node, content_bytes)
    body_node = find_child_by_field_name(class_node, "body")
    docstring = get_docstring_from_python_node(body_node, content_bytes) if body_node else None
    
    base_classes = []
    superclasses_node = find_child_by_field_name(class_node, "superclasses") # This is argument_list node
    if superclasses_node: # and superclasses_node.type == 'argument_list': in newer tree-sitter it is just argument_list
        for sc_node in superclasses_node.named_children:
            base_name = get_node_text(sc_node, content_bytes)
            if base_name: base_classes.append(base_name)
    
    methods = []
    fields = [] 
    if body_node:
        for child in body_node.children:
            if is_node_type(child, LANG, "func_def"):
                # Pass current class FQN as parent_fqn for methods
                method_details = extract_py_function_details(child, file_path, repo_root, content_bytes, parent_fqn=qualified_name)
                if method_details: methods.append(method_details)
            # Basic field extraction (class variables or instance variables in __init__)
            # More robust field extraction would analyze assignments inside __init__ specifically for self.var
            elif is_node_type(child, LANG, "expression_statement"): 
                expression_child = child.named_child(0)
                if expression_child and is_node_type(expression_child, LANG, "assignment"):
                    assign_node = expression_child
                    left_node = find_child_by_field_name(assign_node, "left")
                    field_name_text = get_node_text(left_node, content_bytes)
                    if field_name_text:
                         # Heuristic: if it's a simple identifier, it's a class variable.
                         # If it's self.attr, it's an instance variable (but this node is not inside __init__ here)
                        if left_node.type == 'identifier':
                             fields.append({"name": field_name_text, "type": "unknown", "scope": "class"})

    return {
        "name": class_name, "qualified_name": qualified_name, "kind": "class",
        "source_file": rel_path_str, "language": LANG,
        "line_start": class_node.start_point[0] + 1, "line_end": class_node.end_point[0] + 1,
        "docstring": docstring, "source_code": source_code,
        "base_classes": base_classes, "fields": fields, "methods": methods,
        "dependencies": [], "test_specs_covering": []
    }

def extract_py_test_specifications(func_node, file_path: Path, repo_root: Path, content_bytes: bytes) -> List[Dict[str, Any]]:
    # This function now receives a single test function node
    # The query for test_funcs in config.py identifies the function_definition node.
    # The cli.py passes this node here.
    rel_path_str = str(file_path.relative_to(repo_root))
    specs = []

    name_node = find_child_by_field_name(func_node, "name")
    test_name = get_node_text(name_node, content_bytes)
    if not test_name:
        return []
        
    # Build FQN for test function
    # Tests are usually top-level in their files, so no parent_fqn from class.
    # FQN needs to consider test file path, e.g. tests.module.test_name
    test_module_path = rel_path_str.replace(os.sep, '.').replace('.py', '')
    qualified_name = f"{test_module_path}.{test_name}"


    # print(f"    🧪🐍 Extracting Py test details: {test_name}")
    spec = {
        "id": qualified_name, # Use FQN as ID
        "source_file": rel_path_str,
        "scenario": test_name, # Or derive from docstring
        "qualified_name": qualified_name,
        "language": LANG,
        "line_start": func_node.start_point[0] + 1, 
        "line_end": func_node.end_point[0] + 1,
        "docstring": get_docstring_from_python_node(find_child_by_field_name(func_node, "body"), content_bytes),
        "source_code": get_node_text(func_node, content_bytes),
        "setup": [], "action": {}, "assertions": [] # Placeholders
    }
    # TODO: Extract setup, action, assertions from func_node body
    # For assertions: Iterate body_node.children, look for 'assert_statement' or calls to assert methods.
    specs.append(spec)
    return specs