# src/extract_rust.py
from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import sys

from .ast_utils import (
    find_child_by_field_name, get_node_text,
    get_docstring_from_rust_node, is_node_type, run_query
)

LANG = "rust"

def extract_rs_signature(func_node, content_bytes: bytes) -> Dict[str, Any]:
    sig: Dict[str, Any] = {"params": [], "return_type": "unknown", "async": False, "unsafe": False}
    
    # Check for async/unsafe keywords (simplistic check, might need refinement based on grammar)
    # Rust grammar: function_item children can include "async" "unsafe" "fn"
    for child in func_node.children:
        if child.type == 'async':
            sig["async"] = True
        elif child.type == 'unsafe':
            sig["unsafe"] = True
            
    param_list_node = find_child_by_field_name(func_node, "parameters")
    if param_list_node:
        for param_node in param_list_node.children:
            if param_node.type == 'parameter': # (parameter pattern: type_identifier type: type_identifier)
                pattern_node = find_child_by_field_name(param_node, "pattern")
                type_node = find_child_by_field_name(param_node, "type")
                param_name = get_node_text(pattern_node, content_bytes) if pattern_node else "_unknown_"
                param_type = get_node_text(type_node, content_bytes) if type_node else "unknown"
                sig["params"].append({"name": param_name, "type": param_type})
            elif param_node.type == 'self_parameter': # &self, &mut self, self
                sig["params"].append({"name": "self", "type": get_node_text(param_node, content_bytes)})
            # TODO: Handle more complex patterns, generics, lifetimes

    return_type_node = find_child_by_field_name(func_node, "return_type")
    if return_type_node:
        sig["return_type"] = get_node_text(return_type_node, content_bytes)
    
    return sig

def extract_rs_function_details(func_node, file_path: Path, repo_root: Path, content_bytes: bytes) -> Optional[Dict[str, Any]]:
    rel_path_str = str(file_path.relative_to(repo_root))
    name_node = find_child_by_field_name(func_node, "name")
    func_name = get_node_text(name_node, content_bytes)
    if not func_name:
        return None

    signature = extract_rs_signature(func_node, content_bytes)
    source_code = get_node_text(func_node, content_bytes)
    docstring = get_docstring_from_rust_node(func_node, content_bytes)
    
    # Basic FQN construction for Rust
    module_path_parts = list(Path(rel_path_str).parts)
    if module_path_parts[-1] == 'mod.rs' or module_path_parts[-1] == 'lib.rs':
        module_path_parts.pop()
    elif module_path_parts[-1].endswith('.rs'):
        module_path_parts[-1] = module_path_parts[-1][:-3]
    
    fqn_parts = [part for part in module_path_parts if part and part != 'src']
    # Attempt to get crate name from repo_ir, fallback to repo_name
    # This part is tricky without full context, might need passing repo_name or metadata
    # crate_name = repo_ir.get("project_name", repo_root.name)
    # if fqn_parts and fqn_parts[0] != crate_name:
    #    fqn_parts.insert(0, crate_name) # Crude prepend of crate name
    fqn_parts.append(func_name)
    qualified_name = "::".join(fqn_parts)


    return {
        "name": func_name,
        "qualified_name": qualified_name,
        "source_file": rel_path_str,
        "line_start": func_node.start_point[0] + 1,
        "line_end": func_node.end_point[0] + 1,
        "signature": signature,
        "docstring": docstring,
        "source_code": source_code,
        "logic_ops": [], # Placeholder
        "dependencies": [], # Placeholder
        "test_specs_covering": []
    }

def extract_rs_data_structure(ds_node, file_path: Path, repo_root: Path, content_bytes: bytes) -> Optional[Dict[str, Any]]:
    rel_path_str = str(file_path.relative_to(repo_root))
    kind = "unknown"
    name_node = find_child_by_field_name(ds_node, "name") # 'name' is common for struct_item, enum_item

    if is_node_type(ds_node, LANG, "struct_def"):
        kind = "struct"
    elif is_node_type(ds_node, LANG, "enum_def"):
        kind = "enum"
    
    name = get_node_text(name_node, content_bytes)
    if not name:
        return None

    source_code = get_node_text(ds_node, content_bytes)
    docstring = get_docstring_from_rust_node(ds_node, content_bytes)

    fields = []
    variants = []
    methods = [] # Will be populated by finding associated impl blocks

    if kind == "struct":
        body_node = find_child_by_field_name(ds_node, "body") # field_declaration_list
        if body_node and body_node.type == "field_declaration_list":
            for field_decl_node in body_node.children:
                if field_decl_node.type == "field_declaration":
                    field_name_node = find_child_by_field_name(field_decl_node, "name")
                    field_type_node = find_child_by_field_name(field_decl_node, "type")
                    field_name = get_node_text(field_name_node, content_bytes)
                    field_type = get_node_text(field_type_node, content_bytes)
                    if field_name:
                        fields.append({"name": field_name, "type": field_type or "unknown"})
    elif kind == "enum":
        body_node = find_child_by_field_name(ds_node, "body") # enum_variant_list
        if body_node and body_node.type == "enum_variant_list":
            for variant_node in body_node.children:
                if variant_node.type == "enum_variant":
                    variant_name_node = find_child_by_field_name(variant_node, "name")
                    variant_name = get_node_text(variant_name_node, content_bytes)
                    if variant_name:
                        # TODO: extract variant fields if any (tuple or struct variant)
                        variants.append({"name": variant_name, "fields": []})
    
    # Basic FQN construction
    module_path_parts = list(Path(rel_path_str).parts)
    if module_path_parts[-1] == 'mod.rs' or module_path_parts[-1] == 'lib.rs':
        module_path_parts.pop()
    elif module_path_parts[-1].endswith('.rs'):
        module_path_parts[-1] = module_path_parts[-1][:-3]
    
    fqn_parts = [part for part in module_path_parts if part and part != 'src']
    fqn_parts.append(name)
    qualified_name = "::".join(fqn_parts)

    return {
        "name": name,
        "qualified_name": qualified_name,
        "kind": kind,
        "source_file": rel_path_str,
        "line_start": ds_node.start_point[0] + 1,
        "line_end": ds_node.end_point[0] + 1,
        "docstring": docstring,
        "source_code": source_code,
        "fields": fields,
        "variants": variants,
        "methods": methods, # To be populated later if we parse impl blocks
        "dependencies": [],
        "test_specs_covering": []
    }

def extract_rs_test_specifications(root_node, file_path: Path, repo_root: Path, content_bytes: bytes) -> List[Dict[str, Any]]:
    rel_path_str = str(file_path.relative_to(repo_root))
    specs = []
    test_func_captures = run_query("test_funcs", LANG, root_node)

    processed_nodes = set()
    for node, capture_name in test_func_captures:
        if capture_name == "function" and node.id not in processed_nodes: # node is function_item
            func_node = node
            processed_nodes.add(func_node.id)
            
            name_node = find_child_by_field_name(func_node, "name")
            test_name = get_node_text(name_node, content_bytes)
            if not test_name:
                continue

            # print(f"    🧪🦀 Found Rs test: {test_name}")
            spec = {
                "id": f"{rel_path_str}::{test_name}", # Basic ID
                "source_file": rel_path_str,
                "scenario": test_name,
                "setup": [], "action": {}, "assertions": [] # Placeholders
            }
            specs.append(spec)
    return specs