# src/cli.py
import argparse
import traceback
import sys
from pathlib import Path
import importlib.util 
import os

from .config import (
    LANG_MAP, IGNORE_DIRS, IGNORE_FILES,
    DEFAULT_YAML_OUTPUT_FILENAME, # DEFAULT_LLM_CONTEXT_FILENAME removed as default for CLI arg is None
    SCHEMA_VERSION,
    LANG_CONFIG
)
from .ast_utils import initialize_parsers, parse_code 
from .metadata_parser import parse_project_metadata
from .extract_python import (
    extract_py_data_structure, extract_py_function_details,
    extract_py_test_specifications
)
# from .extract_rust import ( # Rust extractors commented out
#     extract_rs_data_structure, extract_rs_function_details,
#     extract_rs_test_specifications
# )
from .output import save_to_yaml, save_to_llm_context_file
from . import ast_utils as astu

repo_ir = {
    "schema_version": SCHEMA_VERSION,
    "project_name": None,
    "language_primary": "python", 
    "languages_present": set(),
    "metadata": {},
    "components": {} 
}
DEBUG_MODE = False

def find_component_id_for_lib(rel_path_str: str, library_name: str) -> str:
    p = Path(rel_path_str)
    parts = list(p.parts)
    if parts:
        known_suffixes = tuple(LANG_MAP.keys()) + (".pyi",) 
        if parts[-1].endswith(known_suffixes):
            parts[-1] = Path(parts[-1]).stem
        if parts[-1] in ("__init__", "mod", "lib"):
             if len(parts) > 1 : 
                parts.pop()
             elif parts[-1] != library_name : 
                parts.pop()
    if not parts: 
        return library_name 
    return f"{library_name}{'.' if parts else ''}{'.'.join(parts)}"

def process_file(file_path: Path, root_for_analysis: Path, target_name_for_fqn: str):
    global repo_ir, DEBUG_MODE

    if any(part in IGNORE_DIRS for part in file_path.relative_to(root_for_analysis).parts) or \
       file_path.name in IGNORE_FILES:
        if DEBUG_MODE: print(f"  Ignoring (config): {file_path.relative_to(root_for_analysis)}")
        return

    rel_path_to_lib_root = file_path.relative_to(root_for_analysis)
    rel_path_str = str(rel_path_to_lib_root)
    extension = file_path.suffix.lower()
    lang = LANG_MAP.get(extension) 

    if not lang or lang != "python": 
        common_non_code_exts = ['.md', '.txt', '.json', '.yaml', '.toml', '.lock', '.h', '.c', '.cpp', '.cc', '.hpp', '.hh', '.so', '.dylib', '.dll', '.rst', '.html', '.css', '.js', '.rs']
        if DEBUG_MODE and extension not in common_non_code_exts and not file_path.name.startswith('.'):
             print(f"  Skipping (not Python or unmapped): {rel_path_str}")
        return

    # Define is_test_file here, relevant for Python processing block
    is_test_file = "test" in file_path.name.lower() or \
                   any(p.lower() in {"test", "tests"} for p in file_path.parts)

    if DEBUG_MODE: print(f"Processing ({lang}): {rel_path_str} (is_test_file: {is_test_file})")
    repo_ir["languages_present"].add(lang)

    try:
        with open(file_path, 'rb') as f:
            content_bytes = f.read()
        root_node = parse_code(content_bytes, lang)
        if not root_node:
            print(f"  Warning: Could not parse {rel_path_str}. Skipping AST extraction.")
            return

        component_id = find_component_id_for_lib(rel_path_str, target_name_for_fqn)
        if component_id not in repo_ir["components"]:
            repo_ir["components"][component_id] = {
                "component_id": component_id, "component_type": f"{lang}_module",
                "source_path": str(Path(component_id.replace(".", os.sep))),
                "summary": f"Code component: {component_id}",
                "data_structures": [], "functions": [], "test_specifications": []
            }
        
        new_structs, new_funcs, new_tests = [], [], []

        if lang == "python": # This block now correctly uses is_test_file defined above
            for node in root_node.children:
                current_parent_fqn = find_component_id_for_lib(rel_path_str, target_name_for_fqn) 

                if astu.is_node_type(node, lang, "class_def"):
                    struct_data = extract_py_data_structure(node, file_path, root_for_analysis, content_bytes, parent_fqn=current_parent_fqn)
                    if struct_data: 
                        struct_data['language'] = lang
                        new_structs.append(struct_data)
                elif astu.is_node_type(node, lang, "func_def"):
                    name_node = astu.find_child_by_field_name(node, "name")
                    func_name_text = astu.get_node_text(name_node, content_bytes) or ""
                    is_test_func_by_name = func_name_text.startswith("test_")

                    if is_test_file or is_test_func_by_name: 
                        test_data_list = extract_py_test_specifications(node, file_path, root_for_analysis, content_bytes) 
                        if test_data_list: new_tests.extend(test_data_list)
                    else:
                        func_data = extract_py_function_details(node, file_path, root_for_analysis, content_bytes, parent_fqn=current_parent_fqn)
                        if func_data: 
                            func_data['language'] = lang
                            new_funcs.append(func_data)
        
        repo_ir["components"][component_id]["data_structures"].extend(new_structs)
        repo_ir["components"][component_id]["functions"].extend(new_funcs)
        repo_ir["components"][component_id]["test_specifications"].extend(new_tests)

    except Exception as e:
        print(f"ERROR processing file {rel_path_str} from target {target_name_for_fqn}: {type(e).__name__} - {e}")
        if DEBUG_MODE: traceback.print_exc()

def main():
    global repo_ir, DEBUG_MODE
    parser = argparse.ArgumentParser(
        description="LLMOS Lang - Code Deconstruction & Analysis. Analyzes local repositories or installed Python libraries.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo-path", metavar="PATH",
                       help="Path to a local code repository root directory to analyze.")
    group.add_argument("--library", metavar="LIBRARY_NAME", nargs="+",
                       help="Name(s) of installed Python library/libraries to analyze (e.g., mlx requests).")

    parser.add_argument("-o", "--output-yaml", default=DEFAULT_YAML_OUTPUT_FILENAME,
                        help=f"Output YAML IR file path (default: {DEFAULT_YAML_OUTPUT_FILENAME})")
    parser.add_argument("--llm-file", type=str, default=None, 
                        help="Output path for the LLM context text file (e.g., context.txt). If not set, this output is skipped.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable verbose debug printing.")
    parser.add_argument("--include-pyi", action="store_true", help="Include .pyi stub files in Python library analysis.")

    args = parser.parse_args()

    if args.debug:
        DEBUG_MODE = True
        print("Debug mode enabled.")

    try:
        initialize_parsers() 
    except Exception as e:
        print(f"FATAL: Failed to initialize language parsers: {e}")
        if DEBUG_MODE: traceback.print_exc()
        sys.exit(1)
    
    if args.include_pyi:
        if "python" in LANG_CONFIG: 
            LANG_MAP[".pyi"] = "python" 
            print("Including .pyi files for Python analysis.")
        else:
            print("Warning: Python language config not loaded, cannot enable .pyi processing effectively.")

    paths_to_analyze = []
    analysis_target_names = [] 

    if args.repo_path:
        repo_path_obj = Path(args.repo_path).resolve()
        if not repo_path_obj.is_dir():
            print(f"Error: Repository path '{repo_path_obj}' not found or is not a directory.")
            sys.exit(1)
        paths_to_analyze.append(repo_path_obj)
        analysis_target_names.append(repo_path_obj.name) 
        repo_ir["project_name"] = repo_path_obj.name
        repo_ir["metadata"] = parse_project_metadata(repo_path_obj)
        repo_ir["project_name"] = repo_ir["metadata"].get("project_name_from_meta", repo_ir["project_name"])

    elif args.library:
        if DEBUG_MODE:
            print(f"[DEBUG-CLI] Python executable: {sys.executable}")
            print(f"[DEBUG-CLI] sys.path:")
            for p_item in sys.path:
                print(f"  - {p_item}")
        
        for lib_name in args.library:
            print(f"[INFO-CLI] Attempting to locate library: '{lib_name}'")
            lib_root_path = None
            try:
                module_spec = importlib.util.find_spec(lib_name)
                
                if module_spec is None:
                    print(f"Error: Could not find spec for installed library '{lib_name}'. Is it installed correctly in the active Python environment ('{sys.executable}')? Skipping.")
                    continue

                if DEBUG_MODE:
                    print(f"  [DEBUG-CLI] Spec for '{lib_name}':")
                    print(f"    Name: {module_spec.name}")
                    print(f"    Loader: {module_spec.loader}")
                    print(f"    Origin: {module_spec.origin}")
                    has_loc = hasattr(module_spec, 'has_location') and module_spec.has_location
                    print(f"    Has Location: {has_loc}")
                    print(f"    Submodule Search Locations: {module_spec.submodule_search_locations}")
                    try:
                        mod = importlib.import_module(lib_name)
                        print(f"    Direct import __file__: {getattr(mod, '__file__', 'N/A')}")
                        print(f"    Direct import __path__: {getattr(mod, '__path__', 'N/A')}")
                    except Exception as import_err:
                        print(f"    Direct import for debug failed: {import_err}")

                if module_spec.submodule_search_locations:
                    for loc_str in module_spec.submodule_search_locations:
                        potential_path = Path(loc_str)
                        if potential_path.is_dir():
                            lib_root_path = potential_path
                            print(f"  [INFO-CLI] Using submodule_search_location for '{lib_name}': {lib_root_path}")
                            break 
                    if not lib_root_path and DEBUG_MODE:
                         print(f"  [DEBUG-CLI] submodule_search_locations for '{lib_name}' did not yield a valid directory: {module_spec.submodule_search_locations}")
                
                if not lib_root_path and module_spec.origin and module_spec.origin not in ("built-in", "namespace", None):
                    origin_path = Path(module_spec.origin)
                    if origin_path.name == "__init__.py":
                        lib_root_path = origin_path.parent
                        print(f"  [INFO-CLI] Using parent of __init__.py for '{lib_name}': {lib_root_path}")
                    elif origin_path.suffix == ".py":
                        lib_root_path = origin_path.parent
                        print(f"  [INFO-CLI] Using parent directory of single file module '{origin_path.name}' for '{lib_name}': {lib_root_path}")
                    elif origin_path.suffix in ('.so', '.dylib', '.pyd'):
                        print(f"  [WARN-CLI] Library '{lib_name}' origin '{origin_path}' is a compiled file. Static analysis will be limited to .py/.pyi files in its directory: {origin_path.parent}")
                        lib_root_path = origin_path.parent
                
                if lib_root_path and lib_root_path.is_dir():
                    paths_to_analyze.append(lib_root_path)
                    analysis_target_names.append(lib_name) 
                else:
                    print(f"Error: Could not determine a valid directory for library '{lib_name}'. Skipping.")
                    if DEBUG_MODE:
                         print(f"  Final decision for '{lib_name}' path was None. Spec origin: {module_spec.origin}, Submodule_search_locations: {module_spec.submodule_search_locations}")
            except Exception as e:
                print(f"Error trying to locate library '{lib_name}': {type(e).__name__} - {e}")
                if DEBUG_MODE: traceback.print_exc()
        
        if not paths_to_analyze:
            print("No valid libraries found/resolved to analyze. Exiting.")
            sys.exit(1)
        
        repo_ir["project_name"] = f"Libraries Analysis: {', '.join(analysis_target_names)}"
        repo_ir["metadata"] = {"description": f"Static analysis of installed libraries: {', '.join(analysis_target_names)}"}

    print(f"\nAnalyzing targets: {', '.join(analysis_target_names)}")
    if DEBUG_MODE: print(f"  Actual paths to analyze: {paths_to_analyze}")

    for target_path_obj, current_target_name_for_fqn in zip(paths_to_analyze, analysis_target_names):
        print(f"\nProcessing target: {current_target_name_for_fqn} (from path: {target_path_obj})")
        file_count = 0
        target_path_obj = Path(target_path_obj) 
        for item in target_path_obj.rglob('*'): 
            if item.is_file():
                file_count += 1
                process_file(item, target_path_obj, current_target_name_for_fqn)
        print(f"  Scanned {file_count} items in {current_target_name_for_fqn}.")

    repo_ir["language_primary"] = "python" 
    if "python" in repo_ir["languages_present"]:
         repo_ir["languages_present"] = ["python"]
    else:
         repo_ir["languages_present"] = []

    repo_ir["components"] = list(repo_ir["components"].values())

    print(f"\nExtracted information for languages: {', '.join(repo_ir['languages_present'])}")
    if repo_ir["language_primary"]:
        print(f"Primary language set to: {repo_ir['language_primary']}")

    yaml_output_path = Path(args.output_yaml)
    save_to_yaml(repo_ir, yaml_output_path)

    if args.llm_file:
        llm_output_path = Path(args.llm_file)
        save_to_llm_context_file(repo_ir, llm_output_path)

    print("\nAnalysis finished.")

if __name__ == "__main__":
    main()