# src/config.py
# Language configurations, constants, ignore lists

import sys

# tree-sitter Language objects will be loaded here by ast_utils.py
LANG_CONFIG = {}

# Map file extensions to internal language names
LANG_MAP = {
    ".py": "python",
    # ".rs": "rust",
    # Add more as needed
}

# Ignore common directories/files
IGNORE_DIRS = {
    ".git", ".svn", ".hg", "target", "build", "dist", "node_modules",
    "venv", ".venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".vscode", ".idea", "docs", "examples",
    "site-packages", "migrations"
}
IGNORE_FILES = {
    ".gitignore", "LICENSE", "MANIFEST.in", "requirements.txt", "setup.py", "setup.cfg",
    "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", ".DS_Store",
    "pyproject.toml", "Cargo.toml", "Cargo.lock", "package.json", "go.mod",
}

DEFAULT_YAML_OUTPUT_FILENAME = "llmos_ir.yaml"
DEFAULT_LLM_CONTEXT_FILENAME = "llm_context.txt"
SCHEMA_VERSION = "0.2.0"

def load_language_configs():
    global LANG_CONFIG
    if LANG_CONFIG:
        return

    try:
        from tree_sitter_languages import get_language
    except ImportError:
        print("ERROR: tree-sitter-languages is not installed. Please run `pip install tree-sitter-languages`.")
        raise

    # --- Python Config ---
    try:
        py_lang_obj = get_language("python")
        LANG_CONFIG["python"] = {
            "language": py_lang_obj,
            "queries": {
                "functions": """
                    (function_definition name: (identifier) @function.name) @function.definition
                """,
                "classes": """
                    (class_definition name: (identifier) @class.name) @class.definition
                """,
                "docstring": """
                    (expression_statement (string) @docstring)
                """,
                 "test_funcs": """
                    (function_definition name: (identifier) @name
                        (#match? @name "^test_")) @function
                """,
            },
            "node_types": {
                 "func_def": "function_definition", "class_def": "class_definition",
                 "identifier": "identifier", "block": "block",
                 "string": "string", "expression_statement": "expression_statement",
            }
        }
        print("Python tree-sitter config loaded.")
    except Exception as e:
        print(f"Warning: Failed to load Python tree-sitter config: {e}")

    # # --- Rust Config ---
    # try:
    #     rs_lang_obj = get_language("rust")
    #     LANG_CONFIG["rust"] = {
    #         "language": rs_lang_obj,
    #          "queries": { # Keeping basic structure, but commenting out problematic queries
    #              "functions": """
    #                 (function_item name: (identifier) @function.name) @function.definition
    #              """,
    #              "structs": """
    #                 (struct_item name: (type_identifier) @struct.name) @struct.definition
    #              """,
    #              "enums": """
    #                 (enum_item name: (type_identifier) @enum.name) @enum.definition
    #              """,
    #              "impls": """
    #                 (impl_item) @impl.definition
    #              """,
    #              # "doc_comment": """
    #              #    (line_comment (#match? @value "^///[^/]")) @doccomment_outer 
    #              #    (line_comment (#match? @value "^//![^/]")) @doccomment_inner
    #              #    (block_comment) @doccomment_block
    #              # """,
    #              # "test_funcs": """
    #              #    (
    #              #        function_item
    #              #        (attribute_item (path (identifier) @attr_id))
    #              #        name: (identifier) @name
    #              #        (#eq? @attr_id "test")
    #              #    ) @function
    #              # """,
    #         },
    #         "node_types": {
    #              "func_def": "function_item", "struct_def": "struct_item",
    #              "enum_def": "enum_item", "impl_item": "impl_item",
    #              "identifier": "identifier", "type_identifier": "type_identifier",
    #              "field_declaration_list": "field_declaration_list", 
    #              "enum_variant_list": "enum_variant_list", 
    #              "block": "block", 
    #              "line_comment": "line_comment", # Keep for basic comment node type
    #              "block_comment": "block_comment", # Keep for basic comment node type
    #         }
    #     }
    #     print("Rust tree-sitter config loaded (with problematic queries commented out).")
    # except Exception as e:
    #     print(f"Warning: Failed to load Rust tree-sitter config: {e}")

    if not LANG_CONFIG:
        print("ERROR: No language configurations were successfully loaded. Exiting.")
        sys.exit(1)