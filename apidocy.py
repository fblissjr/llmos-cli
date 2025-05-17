import inspect
import os
import importlib
import pkgutil
import sys
import traceback
import argparse # For command-line arguments

# --- Global debug flag, will be set by argparse ---
DEBUG_MODE = False

# --- Helper function to get all submodules (same as before) ---
def get_all_submodules(package, package_name_str):
    global DEBUG_MODE
    submodules = set()
    if not hasattr(package, '__path__'):
        if DEBUG_MODE: print(f"    [DEBUG] Package {package_name_str} has no __path__ for pkgutil.")
        return submodules
    prefix = package_name_str + "."
    if DEBUG_MODE: print(f"    [DEBUG] Walking packages for '{package_name_str}' with prefix '{prefix}' and path {package.__path__}")
    for importer, modname, ispkg in pkgutil.walk_packages(
            path=package.__path__,
            prefix=prefix,
            onerror=lambda name: print(f"  [Warning-pkgutil] Error walking for {name} in {package_name_str}")
    ):
        if not modname.startswith(package_name_str):
            if DEBUG_MODE: print(f"    [DEBUG] Skipping {modname}, no prefix match.")
            continue
        if DEBUG_MODE: print(f"    [DEBUG] >>> Attempting to import: {modname} (ispkg: {ispkg})")
        try:
            module = importlib.import_module(modname)
            if DEBUG_MODE: print(f"    [DEBUG] <<< Successfully imported: {modname}")
            submodules.add(module)
        except Exception as e:
            if DEBUG_MODE: print(f"    [DEBUG] <<< Failed import for {modname}: {e}")
            print(f"  [Warning-Import] Failed to import submodule {modname}: {e}. Skipping.")
            if DEBUG_MODE: traceback.print_exc()
    return submodules

# --- Function to extract docs using inspect ---
def extract_docs_with_inspect(module_obj, base_output_path, visited_modules, library_root_name):
    global DEBUG_MODE
    if module_obj in visited_modules:
        return
    visited_modules.add(module_obj)

    if not module_obj.__name__.startswith(library_root_name):
        return

    module_path_parts = module_obj.__name__.split('.')
    current_module_file_base = os.path.join(base_output_path, *module_path_parts)

    try:
        # For a module file, its content goes into a dir named after the module path
        # For a package (__init__.py), its content also goes into a dir named after it.
        # So, current_module_file_base is the directory.
        if not os.path.exists(current_module_file_base):
            os.makedirs(current_module_file_base)
    except OSError as e:
        print(f"  [Error-OS] Creating directory {current_module_file_base}: {e}. Skipping module.")
        return

    print(f"  Processing module with inspect: {module_obj.__name__} -> {current_module_file_base}/")

    # Module docstring
    module_docstring = inspect.getdoc(module_obj)
    module_doc_filename = os.path.join(current_module_file_base, f"__module_{module_path_parts[-1]}_doc.txt")
    try:
        with open(module_doc_filename, "w", encoding="utf-8") as f:
            f.write(f"# Library: {library_root_name}\n")
            f.write(f"# Module: {module_obj.__name__}\n\n")
            f.write(module_docstring if module_docstring else "[No module docstring]")
            f.write("\n")
    except OSError as e:
        print(f"  [Error-OS] Could not write module docstring for {module_obj.__name__}: {e}")

    # Member docstrings
    try:
        for name, member in inspect.getmembers(module_obj):
            if not (hasattr(member, '__module__') and member.__module__ == module_obj.__name__):
                # Filter to include only members defined in *this* module
                continue

            docstring = inspect.getdoc(member)
            if not docstring: # Skip members without docstrings
                continue

            member_type_str = ""
            filename_prefix = ""
            
            # Sanitize name for filename
            safe_name = "".join(c if c.isalnum() or c in ['_'] else '_' for c in name)
            if not safe_name: safe_name = "unnamed_member"


            if inspect.isclass(member):
                member_type_str = "Class"
                filename_prefix = "class_"
                member_filepath = os.path.join(current_module_file_base, f"{filename_prefix}{safe_name}.txt")
                with open(member_filepath, "w", encoding="utf-8") as f:
                    f.write(f"# Library: {library_root_name}\n")
                    f.write(f"# Module: {module_obj.__name__}\n")
                    f.write(f"# {member_type_str}: {name}\n\n{docstring}\n")
                
                # Document methods of the class
                class_methods_path = os.path.join(current_module_file_base, f"class_{safe_name}_methods")
                methods_found = False
                for method_name, method_obj in inspect.getmembers(member, inspect.isfunction):
                    # Ensure method is defined in this class (not inherited from object/builtins without specific module)
                    if hasattr(method_obj, '__module__') and method_obj.__module__ == module_obj.__name__:
                        method_docstring = inspect.getdoc(method_obj)
                        if method_docstring:
                            if not methods_found: # Create dir only if methods with docs are found
                                if not os.path.exists(class_methods_path): os.makedirs(class_methods_path)
                                methods_found = True
                            safe_method_name = "".join(c if c.isalnum() or c in ['_'] else '_' for c in method_name)
                            if not safe_method_name: safe_method_name = "unnamed_method"
                            method_filepath = os.path.join(class_methods_path, f"method_{safe_method_name}.txt")
                            with open(method_filepath, "w", encoding="utf-8") as fm:
                                fm.write(f"# Library: {library_root_name}\n")
                                fm.write(f"# Module: {module_obj.__name__}\n")
                                fm.write(f"# Class: {name}\n")
                                fm.write(f"# Method: {method_name}\n\n{method_docstring}\n")
            
            elif inspect.isfunction(member): # Catches functions and methods defined at module level
                member_type_str = "Function"
                filename_prefix = "function_"
                member_filepath = os.path.join(current_module_file_base, f"{filename_prefix}{safe_name}.txt")
                with open(member_filepath, "w", encoding="utf-8") as f:
                    f.write(f"# Library: {library_root_name}\n")
                    f.write(f"# Module: {module_obj.__name__}\n")
                    f.write(f"# {member_type_str}: {name}\n\n{docstring}\n")
            
            # Could add inspect.isdatadescriptor for module-level variables if desired,
            # but getdoc() often doesn't work well for them unless they are annotated with docstrings.

    except Exception as e:
        print(f"  [Error-Inspect] Error inspecting members of {module_obj.__name__}: {e}")
        if DEBUG_MODE: traceback.print_exc()

# --- Function to process a single library (using inspect) ---
def process_library_with_inspect(library_name, main_output_folder, visited_modules_cache):
    global DEBUG_MODE
    print(f"\nAttempting to process library '{library_name}' with inspect...")
    top_level_module = None
    try:
        top_level_module = importlib.import_module(library_name)
        version_str = getattr(top_level_module, '__version__', str(getattr(top_level_module, 'VERSION', "N/A")))
        print(f"  Successfully imported {library_name} (version: {version_str})")
    except Exception as e:
        print(f"  [Error-Import] Could not import/process '{library_name}': {e}. Skipping.")
        if DEBUG_MODE: traceback.print_exc()
        return

    all_modules_to_process = {top_level_module}
    if hasattr(top_level_module, '__path__'):
        print(f"  Discovering submodules for package: {library_name}...")
        discovered_submodules = get_all_submodules(top_level_module, library_name)
        all_modules_to_process.update(discovered_submodules)
        print(f"  Found {len(discovered_submodules)} submodules for {library_name} (plus the top-level).")

    sorted_modules = sorted(list(all_modules_to_process), key=lambda m: m.__name__)

    for module_obj_item in sorted_modules:
        extract_docs_with_inspect(module_obj_item, main_output_folder, visited_modules_cache, library_name)

    print(f"Finished processing library: {library_name}")

# --- Aggregation function (generic, can be reused) ---
def aggregate_docs_to_file(source_folder, output_aggregate_file, file_suffix="_doc.txt"):
    print(f"\nAggregating files ending with '{file_suffix}' from '{source_folder}' into '{output_aggregate_file}'...")
    count = 0
    with open(output_aggregate_file, "w", encoding="utf-8") as outfile:
        for root, _, files in os.walk(source_folder):
            for file in sorted(files):
                if file.endswith(file_suffix) or (file_suffix == "_doc.txt" and ("class_" in file or "function_" in file or "__module_" in file) and file.endswith(".txt")): # More specific for inspect
                    filepath = os.path.join(root, file)
                    relative_filepath = os.path.relpath(filepath, source_folder)
                    header_name = relative_filepath.replace(os.sep, ".")
                    # Clean up common parts from header_name for inspect output
                    header_name = header_name.replace(".txt", "").replace("__module_", "module:").replace("class_", "class:").replace("function_", "function:")
                    
                    outfile.write(f"\n\n{'='*15} START: {header_name} {'='*15}\n\n")
                    try:
                        with open(filepath, "r", encoding="utf-8") as infile:
                            outfile.write(infile.read().strip())
                        outfile.write(f"\n\n{'='*15} END: {header_name} {'='*15}\n")
                        count += 1
                    except Exception as e:
                        outfile.write(f"\n\n[ERROR READING FILE: {header_name} - {e}]\n")
                        print(f"  [Error-Aggregation] Reading {filepath}: {e}")
    print(f"Aggregation complete. {count} files written to '{output_aggregate_file}'.")

# --- Main function for inspect-based CLI script ---
def main_inspect():
    global DEBUG_MODE

    parser = argparse.ArgumentParser(
        description="Extracts Python library documentation using the inspect module and aggregates it.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("libraries", metavar="LIBRARY_NAME", type=str, nargs='+', help="Python library names.")
    parser.add_argument("-o", "--output-dir", type=str, default="all_libraries_inspect_docs", help="Base directory for individual doc files.")
    parser.add_argument("-f", "--aggregate-file", type=str, default="llms_inspect_docs.txt", help="Final aggregated text file.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable verbose debug printing.")
    
    args = parser.parse_args()

    if args.debug:
        DEBUG_MODE = True
        print("Debug mode enabled for inspect-based extraction.")

    if not os.path.exists(args.output_dir):
        print(f"Creating output directory: {args.output_dir}")
        os.makedirs(args.output_dir)

    globally_visited_modules_cache = set()

    for lib_name in args.libraries:
        process_library_with_inspect(lib_name, args.output_dir, globally_visited_modules_cache)

    # Suffix for inspect files is more varied, let's use a generic .txt with checks or a common part of the name
    # For this script, the most reliable way is to check for files created.
    # Let's just look for common prefixes or the module doc file for aggregation.
    # The aggregation function was made a bit more specific to handle the varied filenames from inspect.
    aggregate_docs_to_file(args.output_dir, args.aggregate_file)


    print(f"\nAll inspect-based processing finished.")
    print(f"Individual docs are in '{args.output_dir}'.")
    print(f"Combined output is in '{args.aggregate_file}'.")

if __name__ == "__main__":
    main_inspect()