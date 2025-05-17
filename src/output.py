# src/output.py
# Handles saving the extracted Intermediate Representation to YAML and LLM context file.

import yaml
import traceback
from pathlib import Path
from typing import Dict, Any, List, Set, Union # Added Set for type hinting languages_present

# Custom Dumper to prevent !!python/object tags for sets, etc.
# and to handle sets by converting them to sorted lists for consistent YAML.
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True

    def represent_set(self, data):
        return self.represent_list(sorted(list(data)))

NoAliasDumper.add_representer(set, NoAliasDumper.represent_set)

def save_to_yaml(data: Dict[str, Any], output_filepath: Path):
    """Saves the final IR data structure to a YAML file."""
    print(f"\nSaving Intermediate Representation to {output_filepath}...")
    try:
        output_filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(output_filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, Dumper=NoAliasDumper, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
        print(f"YAML IR saved to {output_filepath}")
    except Exception as e:
        print(f"Error writing YAML file '{output_filepath}':")
        traceback.print_exc()
        # As a fallback, you might want to print the raw data if YAML dumping fails.
        # print("\n--- RAW DATA FALLBACK (YAML DUMP FAILED) ---")
        # print(data)
        # print("--- END RAW DATA FALLBACK ---")

def save_to_llm_context_file(data: Dict[str, Any], output_filepath: Path):
    """Saves extracted code and docstrings to a single text file for LLMs."""
    print(f"\nSaving LLM context to {output_filepath}...")
    try:
        output_filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(output_filepath, 'w', encoding='utf-8') as outfile:
            outfile.write(f"# Project: {data.get('project_name', 'Unknown Project')}\n")
            outfile.write(f"## Schema Version: {data.get('schema_version', 'N/A')}\n")
            
            primary_lang = data.get('language_primary', 'N/A')
            outfile.write(f"## Primary Language: {primary_lang}\n")
            
            langs_present_data: Union[Set[str], List[str]] = data.get('languages_present', [])
            if isinstance(langs_present_data, set):
                langs_present_list = sorted(list(langs_present_data))
            else: # Already a list (or other iterable)
                langs_present_list = sorted(list(langs_present_data))
            outfile.write(f"## Languages Present: {', '.join(langs_present_list)}\n\n")

            # --- Metadata Section ---
            metadata = data.get("metadata", {})
            if metadata:
                outfile.write("--- METADATA ---\n")
                if 'project_name_from_meta' in metadata and metadata['project_name_from_meta'] != data.get('project_name'):
                     outfile.write(f"Original Name (from metadata): {metadata.get('project_name_from_meta')}\n")
                outfile.write(f"Version: {metadata.get('version', 'N/A')}\n")
                outfile.write(f"Description: {metadata.get('description', 'N/A')}\n")
                
                authors_list = metadata.get('authors', [])
                if isinstance(authors_list, list):
                    outfile.write(f"Authors: {', '.join(authors_list)}\n")
                else: # Handle if it's a single string or other type
                    outfile.write(f"Authors: {str(authors_list)}\n")

                outfile.write(f"License: {metadata.get('license', 'N/A')}\n") # License can be dict or str
                outfile.write(f"Homepage: {metadata.get('homepage', 'N/A')}\n")
                outfile.write(f"Repository: {metadata.get('repository', 'N/A')}\n")
                
                keywords_list = metadata.get('keywords', [])
                if isinstance(keywords_list, list):
                    outfile.write(f"Keywords: {', '.join(keywords_list)}\n")
                else:
                    outfile.write(f"Keywords: {str(keywords_list)}\n")
                
                if metadata.get("parsed_metadata_files"):
                    outfile.write("\n### Parsed Metadata Files Content:\n")
                    for meta_file in metadata["parsed_metadata_files"]:
                        outfile.write(f"\n#### File: {meta_file['source']}\n")
                        outfile.write("```\n") # Generic code block for metadata content
                        outfile.write(meta_file.get('content', '[Content not available]'))
                        outfile.write("\n```\n")
                
                dependencies = metadata.get("dependencies", [])
                if dependencies:
                    outfile.write("\n### Dependencies:\n")
                    for dep in dependencies:
                        dep_name = dep.get('name', 'Unknown Dependency')
                        dep_version = dep.get('version_spec', 'any version')
                        dep_source = dep.get('source', 'unknown source')
                        outfile.write(f"- {dep_name} (Version: {dep_version}, Source: {dep_source})\n")
                outfile.write("\n") # Extra newline after metadata section

            # --- Code Elements Section ---
            outfile.write("--- CODE ELEMENTS ---\n")
            components_data: Union[Dict[str, Any], List[Dict[str, Any]]] = data.get("components", [])
            
            # Ensure components is a list of dictionaries
            if isinstance(components_data, dict):
                components_list = list(components_data.values())
            elif isinstance(components_data, list):
                components_list = components_data
            else:
                components_list = []

            for component in components_list:
                comp_id = component.get('component_id', 'N/A')
                comp_path = component.get('source_path', '.')
                comp_type = component.get('component_type', 'unknown')
                outfile.write(f"\n### Component (Module/Package): {comp_id}\n")
                outfile.write(f"Path Context: {comp_path}\n") # Use a clearer term
                outfile.write(f"Type: {comp_type}\n")

                # Data Structures (Classes, Structs, Enums)
                for ds_data in component.get("data_structures", []):
                    lang_name = ds_data.get('language', 'code') # Default to 'code' if no language
                    ds_kind = ds_data.get('kind','STRUCTURE').upper()
                    ds_name = ds_data.get('name', 'N/A')
                    outfile.write(f"\n#### {lang_name.upper()} {ds_kind}: {ds_name}\n")
                    outfile.write(f"In File: {ds_data.get('source_file', 'N/A')}\n")
                    outfile.write(f"Qualified Name: {ds_data.get('qualified_name', 'N/A')}\n")
                    outfile.write(f"Lines: {ds_data.get('line_start', '?')}-{ds_data.get('line_end', '?')}\n")
                    outfile.write(f"##### DOCSTRING:\n```\n{(ds_data.get('docstring') or '(No docstring found)')}\n```\n")
                    outfile.write(f"##### SOURCE CODE:\n```{lang_name.lower()}\n{(ds_data.get('source_code') or '# Source code not available')}\n```\n")
                
                # Functions / Methods
                for func_data in component.get("functions", []):
                    lang_name = func_data.get('language', 'code')
                    func_name = func_data.get('name', 'N/A')
                    outfile.write(f"\n#### {lang_name.upper()} FUNCTION: {func_name}\n")
                    outfile.write(f"In File: {func_data.get('source_file', 'N/A')}\n")
                    outfile.write(f"Qualified Name: {func_data.get('qualified_name', 'N/A')}\n")
                    outfile.write(f"Lines: {func_data.get('line_start', '?')}-{func_data.get('line_end', '?')}\n")
                    
                    # Signature formatting
                    sig = func_data.get('signature', {})
                    params_str_parts = []
                    for p in sig.get('params', []):
                        p_name = p.get('name', '_')
                        p_type = p.get('type', 'any')
                        if p_type and p_type != 'unknown':
                            params_str_parts.append(f"{p_name}: {p_type}")
                        else:
                            params_str_parts.append(p_name)
                    params_str = ", ".join(params_str_parts)
                    return_type_str = sig.get('return_type', 'unknown')
                    async_str = "async " if sig.get('async') else ""
                    unsafe_str = "unsafe " if sig.get('unsafe') else "" # For Rust
                    outfile.write(f"Signature: {unsafe_str}{async_str}def {func_name}({params_str}) -> {return_type_str}\n")

                    outfile.write(f"##### DOCSTRING:\n```\n{(func_data.get('docstring') or '(No docstring found)')}\n```\n")
                    outfile.write(f"##### SOURCE CODE:\n```{lang_name.lower()}\n{(func_data.get('source_code') or '# Source code not available')}\n```\n")

                # Test Specifications (optional, can be verbose)
                # if component.get("test_specifications"):
                #     outfile.write("\n--- TEST SPECIFICATIONS ---\n")
                #     for test_spec in component.get("test_specifications", []):
                #         outfile.write(f"\n#### TEST: {test_spec.get('scenario', 'N/A')} (ID: {test_spec.get('id')})\n")
                #         outfile.write(f"Source File: {test_spec.get('source_file')}\n")
                #         # outfile.write(f"Setup: {test_spec.get('setup', [])}\n") # Could be too verbose
                #         # outfile.write(f"Action: {test_spec.get('action', {})}\n")
                #         # outfile.write(f"Assertions: {test_spec.get('assertions', [])}\n")


        print(f"LLM context file saved to {output_filepath}")
    except Exception as e:
        print(f"Error writing LLM context file '{output_filepath}':")
        traceback.print_exc()