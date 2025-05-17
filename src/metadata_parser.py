# src/metadata_parser.py
import toml
import json
from pathlib import Path
from typing import Dict, List, Any

def parse_project_metadata(repo_path: Path) -> Dict[str, Any]:
    """Parses known metadata files and returns extracted info."""
    metadata: Dict[str, Any] = {
        "project_name": repo_path.name, # Default
        "dependencies": [],
        "version": None,
        "description": None,
        "authors": [],
        "license": None,
        "homepage": None,
        "repository": None,
        "keywords": [],
        "parsed_metadata_files": [] # To store content of parsed files
    }
    # print("Parsing project metadata...")

    # --- Cargo.toml (Rust) ---
    cargo_path = repo_path / "Cargo.toml"
    if cargo_path.is_file():
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                content = f.read()
                cargo_data = toml.loads(content) # Use toml.loads for string content
            # print("  Processing Cargo.toml...")
            metadata["parsed_metadata_files"].append({"source": str(cargo_path.relative_to(repo_path)), "content": content})
            
            if 'package' in cargo_data:
                package_info = cargo_data['package']
                metadata["project_name"] = package_info.get('name', metadata["project_name"])
                metadata["version"] = package_info.get('version', metadata["version"])
                metadata["description"] = package_info.get('description', metadata["description"])
                metadata["authors"] = package_info.get('authors', metadata["authors"])
                metadata["license"] = package_info.get('license', metadata["license"])
                metadata["homepage"] = package_info.get('homepage', metadata["homepage"])
                metadata["repository"] = package_info.get('repository', metadata["repository"])
                metadata["keywords"] = package_info.get('keywords', metadata["keywords"])

            if 'dependencies' in cargo_data:
                for name, detail in cargo_data['dependencies'].items():
                     metadata["dependencies"].append({
                        "name": name,
                        "version_spec": str(detail) if isinstance(detail, str) else detail.get("version"),
                        "source": "crates.io" # Assumption
                    })
        except Exception as e:
            print(f"Warning: Failed to parse {cargo_path}: {e}")

    # --- pyproject.toml (Python) ---
    pyproject_path = repo_path / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            with open(pyproject_path, 'r', encoding='utf-8') as f:
                content = f.read()
                pyproject_data = toml.loads(content)
            # print("  Processing pyproject.toml...")
            metadata["parsed_metadata_files"].append({"source": str(pyproject_path.relative_to(repo_path)), "content": content})

            proj_info_section = None
            if 'tool' in pyproject_data and 'poetry' in pyproject_data['tool']:
                proj_info_section = pyproject_data['tool']['poetry']
            elif 'project' in pyproject_data: # PEP 621
                proj_info_section = pyproject_data['project']

            if proj_info_section:
                metadata["project_name"] = proj_info_section.get('name', metadata["project_name"])
                metadata["version"] = proj_info_section.get('version', metadata["version"])
                metadata["description"] = proj_info_section.get('description', metadata["description"])
                # PEP 621 authors is a list of tables, poetry authors is list of strings
                authors_raw = proj_info_section.get('authors', [])
                if authors_raw and isinstance(authors_raw[0], dict): # PEP 621 style
                    metadata["authors"] = [f"{a.get('name', '')} <{a.get('email', '')}>".strip() for a in authors_raw]
                else: # Poetry style (list of strings) or simple list
                    metadata["authors"] = authors_raw

                metadata["license"] = proj_info_section.get('license', metadata["license"]) # Could be a dict or string
                if isinstance(metadata["license"], dict):
                    metadata["license"] = metadata["license"].get("text") or metadata["license"].get("file")


                # Homepage/repository from PEP 621 'urls', or direct poetry keys
                urls = proj_info_section.get('urls', {})
                metadata["homepage"] = urls.get('Homepage') or urls.get('homepage') or proj_info_section.get('homepage', metadata["homepage"])
                metadata["repository"] = urls.get('Repository') or urls.get('repository') or proj_info_section.get('repository', metadata["repository"])
                
                metadata["keywords"] = proj_info_section.get('keywords', metadata["keywords"])

                # Dependencies
                deps_raw = proj_info_section.get('dependencies', {})
                if isinstance(deps_raw, dict): # Poetry style
                    for name, version_spec in deps_raw.items():
                        if name.lower() != 'python':
                            metadata["dependencies"].append({"name": name, "version_spec": str(version_spec), "source": "pypi"})
                elif isinstance(deps_raw, list): # PEP 621 style (list of requirement strings)
                    for req_str in deps_raw:
                        # Basic parsing: 'package_name[extra]>=version'
                        # This is a simplification; proper parsing uses packaging.requirements
                        name_part = req_str.split('[')[0].split('<')[0].split('>')[0].split('=')[0].split('~')[0].strip()
                        if name_part:
                             metadata["dependencies"].append({"name": name_part, "version_spec": req_str, "source": "pypi"})
        except Exception as e:
            print(f"Warning: Failed to parse {pyproject_path}: {e}")

    # print("Metadata parsing done.")
    return metadata