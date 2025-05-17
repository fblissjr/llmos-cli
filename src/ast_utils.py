# src/ast_utils.py
# Tree-sitter setup and generic AST helper functions

import sys
from tree_sitter import Parser, Node
from typing import Dict, Any, Optional, List, Tuple
import textwrap

# Import config loading function, but LANG_CONFIG itself will be populated here
from .config import LANG_CONFIG, load_language_configs

# --- Global Variables ---
parsers: Dict[str, Parser] = {}
_queries_compiled: Dict[str, Dict[str, Any]] = {} # Cache compiled queries

# --- Initialization ---
def initialize_parsers():
    """Load language configs and initialize parsers. Call this once at startup."""
    if not LANG_CONFIG: # Ensure configs are loaded if not already
        load_language_configs()
    
    if not LANG_CONFIG:
        print("FATAL: No language configurations available after attempting to load. Cannot initialize parsers.")
        sys.exit(1)
        
    for lang_name in LANG_CONFIG.keys():
        _initialize_parser(lang_name)

def _initialize_parser(lang_name: str):
    """Initialize parser for a single language if not already done."""
    if lang_name not in parsers:
        if lang_name not in LANG_CONFIG or "language" not in LANG_CONFIG[lang_name]:
            print(f"Warning: Language object for '{lang_name}' not found in LANG_CONFIG. Skipping parser initialization.")
            return None
        try:
            # print(f"Initializing parser for: {lang_name}")
            parser = Parser()
            parser.set_language(LANG_CONFIG[lang_name]["language"])
            parsers[lang_name] = parser
            
            # Pre-compile queries
            _queries_compiled[lang_name] = {}
            for query_name, query_string in LANG_CONFIG[lang_name].get("queries", {}).items():
                try:
                    _queries_compiled[lang_name][query_name] = LANG_CONFIG[lang_name]["language"].query(query_string)
                except Exception as e:
                    print(f"Warning: Failed to compile query '{query_name}' for {lang_name}: {e}")
        except Exception as e:
            print(f"ERROR initializing parser for {lang_name}: {e}")
            return None
    return parsers.get(lang_name)

# --- AST Parsing ---
def parse_code(content_bytes: bytes, lang: str) -> Optional[Node]:
    """Parse code bytes using the appropriate tree-sitter parser."""
    parser = parsers.get(lang)
    if not parser:
        # Attempt to initialize on-the-fly if not already
        parser = _initialize_parser(lang)
        if not parser:
            print(f"Warning: Parser for language '{lang}' not available or failed to initialize.")
            return None
    tree = parser.parse(content_bytes)
    return tree.root_node

# --- AST Traversal & Helpers ---
def get_node_text(node: Optional[Node], content_bytes: bytes) -> Optional[str]:
    """Safely get UTF-8 text from a tree-sitter node."""
    if node and content_bytes is not None:
        if node.start_byte < node.end_byte <= len(content_bytes):
            try:
                return content_bytes[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
            except IndexError:
                # This should ideally not happen if start_byte < end_byte <= len is true
                print(f"Warning: IndexError accessing node text. Bytes:{len(content_bytes)} Range: {node.start_byte}-{node.end_byte}")
                return "<text_extraction_error:index>"
        else:
            # This often means an issue with the node itself (e.g. a virtual node) or an empty match
            # print(f"Warning: Invalid node range or empty node. Bytes:{len(content_bytes)} Node: {node.type} Range: {node.start_byte}-{node.end_byte}")
            return "" # Return empty string for invalid ranges or empty nodes
    return None

def run_query(query_key: str, lang: str, node: Node) -> List[Tuple[Node, str]]:
    """Run a pre-compiled tree-sitter query. Returns list of (node, capture_name) tuples."""
    lang_queries = _queries_compiled.get(lang, {})
    query = lang_queries.get(query_key)
    if query and node:
        try:
            return query.captures(node)
        except Exception as e:
            print(f"Error running query '{query_key}' (lang: {lang}) on node type {node.type}: {e}")
    return []

def get_lang_config_val(lang: str, key: str, default: Any = None) -> Any:
    """Get language specific config value (e.g., node types dict)."""
    if lang not in LANG_CONFIG:
        # print(f"Warning: Language config not loaded for {lang}")
        return default
    return LANG_CONFIG[lang].get(key, default)

def is_node_type(node: Optional[Node], lang: str, type_key: str) -> bool:
    """Check if node matches a configured type name for the language."""
    if not node: return False
    node_types_map = get_lang_config_val(lang, "node_types", {})
    expected_type_name = node_types_map.get(type_key)
    return expected_type_name is not None and node.type == expected_type_name

def find_child_by_field_name(node: Optional[Node], field_name: str) -> Optional[Node]:
    """Helper to get child by field name, handling None."""
    if not node: return None
    return node.child_by_field_name(field_name)

def get_docstring_from_python_node(body_node: Optional[Node], content_bytes: bytes) -> Optional[str]:
    if not body_node or not is_node_type(body_node, "python", "block") or not body_node.named_children:
        return None

    first_statement = body_node.named_children[0]
    
    if is_node_type(first_statement, "python", "expression_statement") and \
       first_statement.named_children and \
       is_node_type(first_statement.named_children[0], "python", "string"): # Check the child of expression_statement
        
        string_node_container = first_statement.named_children[0] # This is the 'string' node
        
        # The 'string' node can have multiple children if it's a concatenated string
        # e.g., (string (string_content) (string_content)) for "abc" "def"
        # or children like '"""', (string_content), '"""' for triple-quoted.
        docstring_parts = []
        for child_string_node in string_node_container.children:
            # We want the actual content, not the quote characters themselves.
            # Tree-sitter python grammar typically has 'string_content' or 'escape_sequence'
            # as children of 'string' for the actual text.
            # The exact child type name for content might vary slightly based on tree-sitter-python version or string type.
            # A more robust way is to check if it's NOT a quote character.
            node_type_str = child_string_node.type
            if node_type_str not in ('"""', "'''", '"', "'", 'r"', "r'", 'u"', "u'", 'f"', "f'"): # Skip quotes and prefixes
                text_part = get_node_text(child_string_node, content_bytes)
                if text_part is not None:
                    docstring_parts.append(text_part)
        
        raw_docstring = "".join(docstring_parts)
        
        if raw_docstring:
            # Clean common quotes if they were accidentally included by get_node_text
            # if (raw_docstring.startswith('"""') and raw_docstring.endswith('"""')) or \
            #    (raw_docstring.startswith("'''") and raw_docstring.endswith("'''")):
            #    if len(raw_docstring) >= 6:
            #        raw_docstring = raw_docstring[3:-3]
            # elif (raw_docstring.startswith('"') and raw_docstring.endswith('"')) or \
            #      (raw_docstring.startswith("'") and raw_docstring.endswith("'")):
            #    if len(raw_docstring) >= 2:
            #        raw_docstring = raw_docstring[1:-1]
            
            # Unindent the docstring
            return textwrap.dedent(raw_docstring).strip()
            
    return None

def get_docstring_from_rust_node(item_node: Node, content_bytes: bytes) -> Optional[str]:
    """
    Extracts a docstring from a Rust item (function, struct, enum).
    Rust docstrings are comments like `/// outer` or `/** outer */` or `//! inner`.
    This function looks for preceding comment nodes or inner comments.
    """
    doc_lines = []

    # Check for outer doc comments (/// or /**)
    # These are typically sibling comment nodes *before* the item node
    prev_sibling = item_node.prev_named_sibling
    temp_doc_lines = []
    while prev_sibling and prev_sibling.type in ("line_comment", "block_comment"):
        comment_text = get_node_text(prev_sibling, content_bytes)
        if comment_text:
            if prev_sibling.type == "line_comment" and comment_text.startswith("///"):
                temp_doc_lines.append(comment_text[3:].strip()) # Remove /// and space
            elif prev_sibling.type == "block_comment" and comment_text.startswith("/**") and comment_text.endswith("*/"):
                # Basic block comment cleaning
                cleaned_block = comment_text[3:-2].strip()
                # Handle potential * prefixes on new lines for block comments
                block_lines = [line.strip().lstrip('*').strip() for line in cleaned_block.split('\n')]
                temp_doc_lines.extend(block_lines)
        prev_sibling = prev_sibling.prev_named_sibling
    doc_lines.extend(reversed(temp_doc_lines)) # Comments are found in reverse order

    # Check for inner doc comments (//! or /*!) within the item's direct children (e.g. first in a block)
    # This is more complex as it depends on the item's structure.
    # For a simple start, let's check the first children of a block if the item has one.
    block_node = None
    if item_node.type == "function_item":
        block_node = find_child_by_field_name(item_node, "body")
    elif item_node.type in ("struct_item", "enum_item"):
        # struct body is field_declaration_list, enum body is enum_variant_list
        # Inner comments are usually at the top of these.
        if item_node.named_child_count > 0:
             # Check children of the item itself for comments before other significant nodes
            for child in item_node.named_children:
                if child.type in ("line_comment", "block_comment"):
                    comment_text = get_node_text(child, content_bytes)
                    if comment_text:
                        if child.type == "line_comment" and comment_text.startswith("//!"):
                            doc_lines.append(comment_text[3:].strip())
                        elif child.type == "block_comment" and comment_text.startswith("/*!") and comment_text.endswith("*/"):
                            cleaned_block = comment_text[3:-2].strip()
                            block_lines = [line.strip().lstrip('*').strip() for line in cleaned_block.split('\n')]
                            doc_lines.extend(block_lines)
                # Stop if we hit a non-comment significant child first
                elif child.type not in ('attribute_item', '{', '}'): # Heuristic
                    break


    return "\n".join(doc_lines).strip() if doc_lines else None