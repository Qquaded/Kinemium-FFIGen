#!/usr/bin/env python3
"""
C to Zune FFI Binding Generator

This script parses C header files and generates Luau FFI bindings
compatible with zune.ffi, creating struct definitions, function bindings,
and constant tables.

Usage:
    python c_to_luau_ffi.py input.h --output-dir ./bindings --lib-name mylib
    python c_to_luau_ffi.py --github https://github.com/user/repo --lib-name mylib
-- Made by devcell
"""

import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
import urllib.request
import urllib.parse
import json
import tempfile
import shutil


@dataclass
class StructField:
    name: str
    type: str
    is_array: bool = False
    array_size: Optional[str] = None
    is_pointer: bool = False


@dataclass
class Struct:
    name: str
    fields: List[StructField]
    comment: Optional[str] = None


@dataclass
class Function:
    name: str
    return_type: str
    parameters: List[Tuple[str, str]]  # (type, name)
    comment: Optional[str] = None


@dataclass
class Enum:
    name: Optional[str]
    values: Dict[str, int] = field(default_factory=dict)


@dataclass
class Define:
    name: str
    value: str


class GitHubFetcher:
    """Fetch header files from GitHub repositories"""
    
    @staticmethod
    def parse_github_url(url: str) -> Tuple[str, str, Optional[str], Optional[str]]:
        """
        Parse GitHub URL to extract owner, repo, branch, and path
        Examples:
            https://github.com/raysan5/raylib
            https://github.com/raysan5/raylib/tree/master
            https://github.com/raysan5/raylib/tree/master/src
        """
        # Remove trailing slash
        url = url.rstrip('/')
        
        # Handle different GitHub URL formats
        patterns = [
            r'github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)',  # Full path with branch
            r'github\.com/([^/]+)/([^/]+)/tree/([^/]+)',       # Just branch
            r'github\.com/([^/]+)/([^/]+)',                     # Just repo
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                groups = match.groups()
                owner = groups[0]
                repo = groups[1].replace('.git', '')
                branch = groups[2] if len(groups) > 2 else None
                path = groups[3] if len(groups) > 3 else None
                return owner, repo, branch, path
        
        raise ValueError(f"Invalid GitHub URL: {url}")
    
    @staticmethod
    def fetch_directory_contents(owner: str, repo: str, path: str = '', branch: str = 'main') -> List[Dict]:
        """Fetch directory contents from GitHub API"""
        # Try multiple common branch names
        branches_to_try = [branch, 'main', 'master']
        
        for try_branch in branches_to_try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            if try_branch:
                api_url += f"?ref={try_branch}"
            
            try:
                request = urllib.request.Request(api_url)
                request.add_header('Accept', 'application/vnd.github.v3+json')
                
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode())
                    print(f"Successfully fetched from branch: {try_branch}")
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 404 and try_branch != branches_to_try[-1]:
                    continue  # Try next branch
                print(f"Error fetching from GitHub API: {e}")
                if e.code == 403:
                    print("Note: GitHub API rate limit may be exceeded. Try again later or use authentication.")
                raise
        
        raise ValueError(f"Could not fetch repository contents from any common branch")
    
    @staticmethod
    def download_file(url: str) -> str:
        """Download file content from URL"""
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode('utf-8')
    
    @staticmethod
    def fetch_headers_from_github(github_url: str, include_subdir: str = 'include') -> Path:
        """
        Fetch header files from a GitHub repository
        Returns a temporary directory path containing the downloaded headers
        """
        owner, repo, branch, url_path = GitHubFetcher.parse_github_url(github_url)
        
        # Use provided branch or default
        if not branch:
            branch = 'main'
        
        # Determine the path to fetch
        if url_path:
            fetch_path = url_path
        else:
            fetch_path = include_subdir
        
        print(f"Fetching headers from: {owner}/{repo}")
        print(f"Branch: {branch}")
        print(f"Path: {fetch_path}")
        
        # Create temporary directory
        temp_dir = Path(tempfile.mkdtemp(prefix='github_headers_'))
        
        try:
            # Fetch directory contents
            contents = GitHubFetcher.fetch_directory_contents(owner, repo, fetch_path, branch)
            
            # Download all .h files
            header_count = 0
            for item in contents:
                if item['type'] == 'file' and item['name'].endswith('.h'):
                    print(f"  Downloading: {item['name']}")
                    file_content = GitHubFetcher.download_file(item['download_url'])
                    
                    output_file = temp_dir / item['name']
                    output_file.write_text(file_content)
                    header_count += 1
            
            if header_count == 0:
                raise ValueError(f"No header files found in {fetch_path}")
            
            print(f"Downloaded {header_count} header file(s)")
            return temp_dir
            
        except Exception as e:
            # Clean up temp directory on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise


class CToLuauFFI:
    """Converts C header files to Luau FFI bindings"""
    
    # Type mapping from C to Luau FFI types
    TYPE_MAP = {
        'void': 'ffi.types.void',
        'char': 'ffi.types.i8',
        'unsigned char': 'ffi.types.u8',
        'short': 'ffi.types.i16',
        'unsigned short': 'ffi.types.u16',
        'int': 'ffi.types.i32',
        'unsigned int': 'ffi.types.u32',
        'long': 'ffi.types.i64',
        'unsigned long': 'ffi.types.u64',
        'long long': 'ffi.types.i64',
        'unsigned long long': 'ffi.types.u64',
        'float': 'ffi.types.float',
        'double': 'ffi.types.double',
        'bool': 'ffi.types.u8',
        'int8_t': 'ffi.types.i8',
        'uint8_t': 'ffi.types.u8',
        'int16_t': 'ffi.types.i16',
        'uint16_t': 'ffi.types.u16',
        'int32_t': 'ffi.types.i32',
        'uint32_t': 'ffi.types.u32',
        'int64_t': 'ffi.types.i64',
        'uint64_t': 'ffi.types.u64',
        'size_t': 'ffi.types.u64',
    }
    
    def __init__(self):
        self.structs: Dict[str, Struct] = {}
        self.functions: Dict[str, Function] = {}
        self.typedefs: Dict[str, str] = {}
        self.enums: List[Enum] = []
        self.defines: List[Define] = []
        self.known_types: Set[str] = set()
        
    def parse_header(self, header_path: Path) -> None:
        """Parse a C header file"""
        content = header_path.read_text(encoding='utf-8', errors='ignore')
        
        # Remove comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        
        # Parse defines
        self._parse_defines(content)
        
        # Parse enums
        self._parse_enums(content)
        
        # Parse typedefs
        self._parse_typedefs(content)
        
        # Parse structs
        self._parse_structs(content)
        
        # Parse function declarations
        self._parse_functions(content)
    
    def _parse_defines(self, content: str) -> None:
        """Parse #define constants"""
        define_pattern = r'#define\s+([A-Z_][A-Z0-9_]*)\s+(.+?)(?:\n|$)'
        
        for match in re.finditer(define_pattern, content):
            name, value = match.groups()
            value = value.strip()
            
            # Skip function-like macros and preprocessor directives
            if '(' in name or '\\' in value or value.startswith('('):
                continue
            
            # Skip non-numeric values
            if not any(c.isdigit() for c in value):
                continue
            
            # Try to evaluate simple expressions
            try:
                # Handle hex values
                if value.startswith('0x') or value.startswith('0X'):
                    eval_value = str(int(value, 16))
                    self.defines.append(Define(name=name, value=eval_value))
                # Handle octal values
                elif value.startswith('0') and len(value) > 1 and value[1].isdigit():
                    eval_value = str(int(value, 8))
                    self.defines.append(Define(name=name, value=eval_value))
                # Handle decimal and simple expressions
                elif value.replace('.', '').replace('-', '').replace('+', '').replace('e', '').replace('E', '').replace('f', '').replace('F', '').replace('L', '').replace('U', '').isdigit():
                    self.defines.append(Define(name=name, value=value.rstrip('fFuUlL')))
                # Handle shifted values like (1 << 5) or bitwise operations
                elif re.match(r'^[\d\s\(\)\<\>\|\&\^\+\-\*\/]+$', value):
                    try:
                        eval_value = str(eval(value))
                        self.defines.append(Define(name=name, value=eval_value))
                    except:
                        pass
            except:
                pass
    
    def _parse_enums(self, content: str) -> None:
        """Parse enum declarations"""
        # Match enum definitions
        enum_pattern = r'typedef\s+enum\s*{([^}]*)}\s*(\w+)\s*;'
        
        for match in re.finditer(enum_pattern, content, re.DOTALL):
            body, name = match.groups()
            values = self._parse_enum_values(body)
            self.enums.append(Enum(name=name, values=values))
        
        # Also match anonymous enums
        enum_pattern2 = r'enum\s+(\w+)?\s*{([^}]*)};'
        for match in re.finditer(enum_pattern2, content, re.DOTALL):
            name, body = match.groups()
            values = self._parse_enum_values(body)
            self.enums.append(Enum(name=name, values=values))
    
    def _parse_enum_values(self, body: str) -> Dict[str, int]:
        """Parse enum values"""
        values = {}
        current_value = 0
        
        for line in body.split(','):
            line = line.strip()
            if not line:
                continue
            
            # Remove comments
            line = re.sub(r'/\*.*?\*/', '', line)
            line = re.sub(r'//.*', '', line)
            line = line.strip()
            
            if not line:
                continue
            
            # Check for explicit value
            if '=' in line:
                parts = line.split('=', 1)
                enum_name = parts[0].strip()
                value_str = parts[1].strip()
                
                # Try to evaluate the value
                try:
                    # Handle hex values
                    if value_str.startswith('0x') or value_str.startswith('0X'):
                        current_value = int(value_str, 16)
                    # Handle bit shifts and simple expressions
                    elif '<<' in value_str or '>>' in value_str:
                        current_value = eval(value_str)
                    else:
                        current_value = int(value_str)
                except:
                    # If we can't evaluate, just increment
                    current_value += 1
                
                values[enum_name] = current_value
                current_value += 1
            else:
                # No explicit value, use current
                values[line] = current_value
                current_value += 1
        
        return values
    
    def _parse_typedefs(self, content: str) -> None:
        """Parse typedef declarations"""
        # Simple typedefs
        typedef_pattern = r'typedef\s+([^;]+?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;'
        
        for match in re.finditer(typedef_pattern, content):
            original, alias = match.groups()
            original = original.strip()
            
            # Skip struct/enum typedefs (handled separately)
            if 'struct' in original or 'enum' in original or '{' in original:
                continue
            
            self.typedefs[alias] = original
            
            # If it's a pointer typedef, mark it
            if '*' in original:
                self.known_types.add(alias)
    
    def _parse_structs(self, content: str) -> None:
        """Parse struct definitions"""
        # Match typedef struct with name before braces: typedef struct StructName { ... } StructName;
        struct_pattern1 = r'typedef\s+struct\s+(\w+)\s*{([^}]*)}\s*(\w+)\s*;'
        for match in re.finditer(struct_pattern1, content, re.DOTALL):
            struct_name, body, typedef_name = match.groups()
            fields = self._parse_struct_fields(body)
            # Use the typedef name as the primary name
            self.structs[typedef_name] = Struct(name=typedef_name, fields=fields)
            self.known_types.add(typedef_name)
            if struct_name != typedef_name:
                self.known_types.add(struct_name)
        
        # Match typedef struct without name: typedef struct { ... } StructName;
        struct_pattern2 = r'typedef\s+struct\s*{([^}]*)}\s*(\w+)\s*;'
        for match in re.finditer(struct_pattern2, content, re.DOTALL):
            body, name = match.groups()
            if name not in self.structs:
                fields = self._parse_struct_fields(body)
                self.structs[name] = Struct(name=name, fields=fields)
                self.known_types.add(name)
        
        # Also match regular struct definitions: struct StructName { ... };
        struct_pattern3 = r'struct\s+(\w+)\s*{([^}]*)};'
        for match in re.finditer(struct_pattern3, content, re.DOTALL):
            name, body = match.groups()
            if name not in self.structs:
                fields = self._parse_struct_fields(body)
                self.structs[name] = Struct(name=name, fields=fields)
                self.known_types.add(name)
    
    def _parse_struct_fields(self, body: str) -> List[StructField]:
        """Parse fields within a struct body"""
        fields = []

        # Split by semicolons and process each field
        for line in body.split(';'):
            line = line.strip()
            if not line:
                continue

            # Remove comments
            line = re.sub(r'/\*.*?\*/', '', line)
            line = re.sub(r'//.*', '', line)
            line = line.strip()

            if not line:
                continue

            # Check for function pointer
            func_ptr_match = re.match(r'(.+?)\s*\(\s*\*\s*(\w+)\s*\)\s*\(([^)]*)\)', line)
            if func_ptr_match:
                # Function pointer, treat as pointer
                field_name = func_ptr_match.group(2)
                fields.append(StructField(
                    name=field_name,
                    type='void',  # Not used for pointers
                    is_pointer=True
                ))
                continue

            line_clean = line

            # Check for bitfield (skip)
            if ':' in line_clean:
                continue

            # Check for array
            array_match = re.match(r'(.+?)\s+(\w+)\s*\[([^\]]+)\]', line)
            if array_match:
                field_type, field_name, array_size = array_match.groups()
                is_pointer = '*' in field_type
                field_type = field_type.replace('*', '').strip()
                array_size = array_size.strip()
                # Resolve array size if it's a define
                if array_size in self.defines:
                    array_size = self.defines[array_size]
                fields.append(StructField(
                    name=field_name,
                    type=field_type,
                    is_array=True,
                    array_size=array_size,
                    is_pointer=is_pointer
                ))
            else:
                # Check for pointer
                is_pointer = '*' in line
                line_clean = line.replace('*', ' ').strip()

                # Handle multiple fields on same line (e.g., "int a, b, c")
                # Split by comma to handle multiple field declarations
                if ',' in line_clean:
                    parts = line_clean.split()
                    if len(parts) >= 2:
                        field_type = parts[0]
                        field_names = ' '.join(parts[1:]).split(',')
                        for field_name in field_names:
                            field_name = field_name.strip().rstrip(';').strip()
                            if field_name:
                                fields.append(StructField(
                                    name=field_name,
                                    type=field_type.strip(),
                                    is_pointer=is_pointer
                                ))
                else:
                    # Regular single field
                    parts = line_clean.rsplit(None, 1)
                    if len(parts) == 2:
                        field_type, field_name = parts
                        # Clean up any stray parentheses or invalid chars
                        field_name = field_name.strip('()').rstrip(';').strip()
                        if field_name:
                            fields.append(StructField(
                                name=field_name,
                                type=field_type.strip(),
                                is_pointer=is_pointer
                            ))

        return fields
    
    def _parse_functions(self, content: str) -> None:
        """Parse function declarations and definitions"""
        # Match function declarations and definitions (ending with ; or {)
        func_pattern = r'([A-Za-z_][A-Za-z0-9_\s\*]*?)\s*\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*[;{]'

        for match in re.finditer(func_pattern, content):
            return_type, func_name, params = match.groups()

            # Skip if it's a typedef or control structure
            if 'typedef' in return_type or not func_name or func_name in ['if', 'while', 'for', 'switch', 'return'] or '...' in params:
                continue

            return_type = return_type.strip()

            # Strip common macros or decorators
            return_type = re.sub(r'\b[A-Z_][A-Z0-9_]*API\b', '', return_type)
            return_type = re.sub(r'__declspec\([^)]*\)', '', return_type)
            return_type = re.sub(r'\bextern\s+"C"\b', '', return_type)
            return_type = re.sub(r'\b(?:extern|static|inline)\b', '', return_type)

            return_type = return_type.strip()

            if not return_type:
                continue

            parameters = self._parse_parameters(params)
            self.functions[func_name] = Function(
                name=func_name,
                return_type=return_type,
                parameters=parameters
            )
    
    def _parse_parameters(self, params_str: str) -> List[Tuple[str, str]]:
        """Parse function parameters"""
        parameters = []
        arg_index = 0

        # Empty params or just void - return empty list
        params_str = params_str.strip()
        if not params_str or params_str == 'void':
            return parameters

        for param in params_str.split(','):
            param = param.strip()
            if not param or param == 'void':
                continue

            # Remove const
            param = param.replace('const', '').strip()

            # Split into type and name
            parts = param.rsplit(None, 1)
            if len(parts) == 2:
                param_type, param_name = parts
                param_name = param_name.lstrip('*')
                if not param_name:
                    param_name = f"arg{arg_index}"
                    arg_index += 1
                parameters.append((param_type.strip(), param_name))
            elif len(parts) == 1:
                # Just type, no name
                param_name = f"arg{arg_index}"
                arg_index += 1
                parameters.append((parts[0].strip(), param_name))

        return parameters
    
    def _convert_type(self, c_type: str) -> str:
        """Convert C type to Luau FFI type"""
        # Remove const and other qualifiers
        c_type = c_type.replace('const', '').strip()

        # Check if it's a pointer
        is_pointer = '*' in c_type
        c_type = c_type.replace('*', '').strip()

        # Resolve typedefs
        if c_type in self.typedefs:
            c_type = self.typedefs[c_type]

        # Check if it's a known struct
        if c_type in self.known_types:
            return 'ffi.types.pointer'

        # Check type map
        if c_type in self.TYPE_MAP:
            ffi_type = self.TYPE_MAP[c_type]
        else:
            # Unknown type, assume pointer
            ffi_type = 'ffi.types.pointer'

        # If original was a pointer, override to pointer type
        if is_pointer:
            return 'ffi.types.pointer'

        return ffi_type
    
    def _convert_struct_field_type(self, field: StructField) -> str:
        """Convert struct field to Luau FFI type declaration"""
        if field.is_pointer:
            return 'ffi.types.pointer'
        
        if field.is_array:
            base_type = self._convert_type(field.type)
            return f"{base_type}:array({field.array_size})"
        
        # Check if it's a known struct type
        if field.type in self.structs:
            return field.type
        
        return self._convert_type(field.type)
    
    def generate_structs_file(self, fields_per_line: int = 4) -> str:
        """Generate the structs.luau file"""
        lines = [
            "--!strict",
            "--!optimize 2",
            "--!native",
            "",
            "local ffi = zune.ffi",
            "",
            "-- Basic type aliases",
            "local int = ffi.types.i32",
            "local uint = ffi.types.u32",
            "local bool = ffi.types.u8",
            "local float = ffi.types.float",
            "local double = ffi.types.double",
            "",
        ]
        
        # Generate struct definitions
        for struct_name, struct in self.structs.items():
            if struct.comment:
                lines.append(f"-- {struct.comment}")
            lines.append(f"local {struct_name} = ffi.struct({{")

            # Group fields into lines for readability
            for i in range(0, len(struct.fields), fields_per_line):
                line_fields = struct.fields[i:i + fields_per_line]
                field_strs = []
                for field in line_fields:
                    field_type = self._convert_struct_field_type(field)
                    field_strs.append(f"{{ {field.name} = {field_type} }}")
                lines.append(f"\t{', '.join(field_strs)},")

            lines.append("})")
            lines.append(f"export type {struct_name} = typeof({struct_name}:new({{}}))")
            lines.append("")
        
        # Export table
        lines.append("local structs = {")
        for struct_name in self.structs.keys():
            lines.append(f"\t{struct_name} = {struct_name},")
        lines.append("}")
        lines.append("")
        lines.append("return structs")
        
        return '\n'.join(lines)
    
    def _convert_type_to_luau(self, c_type: str) -> str:
        """Convert C type to Luau type annotation"""
        # Remove const and other qualifiers
        c_type = c_type.replace('const', '').strip()
        
        # Check if it's a pointer
        is_pointer = '*' in c_type
        c_type = c_type.replace('*', '').strip()
        
        # Basic type mappings to Luau types
        luau_type_map = {
            'void': '()',
            'char': 'int',
            'unsigned char': 'int',
            'short': 'int',
            'unsigned short': 'int',
            'int': 'int',
            'unsigned int': 'int',
            'long': 'int',
            'unsigned long': 'int',
            'long long': 'int',
            'unsigned long long': 'int',
            'float': 'float',
            'double': 'number',
            'bool': 'bool',
            'int8_t': 'int',
            'uint8_t': 'int',
            'int16_t': 'int',
            'uint16_t': 'int',
            'int32_t': 'int',
            'uint32_t': 'int',
            'int64_t': 'int',
            'uint64_t': 'int',
            'size_t': 'int',
        }
        
        # Handle string pointers
        if c_type == 'char' and is_pointer:
            return 'cstring'
        
        # If it's a pointer, return FFIPointer
        if is_pointer:
            return 'FFIPointer'
        
        # Check if it's a known struct
        if c_type in self.structs:
            return c_type
        
        # Check basic type map
        if c_type in luau_type_map:
            return luau_type_map[c_type]
        
        # Unknown type, default to any or FFIPointer
        return 'FFIPointer'
    
    def generate_funcs_file(self) -> str:
        """Generate the funcs.luau file with type annotations"""
        lines = [
            "local ffi = zune.ffi",
            "",
            "-- Type aliases for FFI",
            "type int = number",
            "type float = number",
            "type bool = boolean",
            "type cstring = string",
            "type FFIPointer = typeof(ffi.types.pointer)",
            "",
        ]
        
        # Add imports for struct types
        if self.structs:
            struct_imports = []
            for struct_name in sorted(self.structs.keys()):
                struct_imports.append(struct_name)
            
            lines.append("-- Import struct types")
            lines.append("local structs = require('./structs')")
            for struct_name in struct_imports:
                lines.append(f"type {struct_name} = structs.{struct_name}")
            lines.append("")
        
        # Generate Fns type
        lines.append("export type Fns = {")
        
        for func_name, func in sorted(self.functions.items()):
            if func.comment:
                lines.append(f"\t-- {func.comment}")
            # Build parameter list with types
            params = []
            for param_type, param_name in func.parameters:
                if not param_name:
                    param_name = "arg"
                luau_type = self._convert_type_to_luau(param_type)
                params.append(f"{param_name}: {luau_type}")

            params_str = ", ".join(params) if params else ""

            # Get return type
            return_luau_type = self._convert_type_to_luau(func.return_type)
            if return_luau_type == '()':
                return_str = "()"
            else:
                return_str = return_luau_type

            lines.append(f"\t{func_name}: ({params_str}) -> {return_str},")
        
        lines.append("}")
        lines.append("")
        
        # Generate actual function table
        lines.append("local funcs = {")
        
        for func_name, func in self.functions.items():
            # Build args list
            args = []
            for param_type, param_name in func.parameters:
                ffi_type = self._convert_type(param_type)
                # Never add void to args
                if ffi_type != 'ffi.types.void':
                    args.append(ffi_type)
            
            args_str = ", ".join(args) if args else ""
            return_type = self._convert_type(func.return_type)
            
            lines.append(f"\t{func_name} = {{ returns = {return_type}, args = {{ {args_str} }} }},")
        
        lines.append("}")
        lines.append("")
        lines.append("return funcs")
        
        return '\n'.join(lines)
    
    def generate_constants_file(self) -> str:
        """Generate a constants.luau file with enums and defines"""
        lines = [
            "--!strict",
            "--!optimize 2",
            "",
            "local constants = {",
        ]

        def to_hex(value):
            try:
                int_val = int(value)
                return hex(int_val)
            except ValueError:
                return value

        # Process enums
        for enum in self.enums:
            if enum.name:
                # Skip if name contains invalid characters
                if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', enum.name):
                    continue

                lines.append(f"\t{enum.name} = {{")
                for value_name, value in enum.values.items():
                    # Skip invalid identifiers
                    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', value_name):
                        continue
                    lines.append(f"\t\t{value_name} = {to_hex(value)},")
                lines.append("\t},")
                lines.append("")
            else:
                # Anonymous enum, add directly
                for value_name, value in enum.values.items():
                    # Skip invalid identifiers
                    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', value_name):
                        continue
                    lines.append(f"\t{value_name} = {to_hex(value)},")

        # Process defines
        if self.defines:
            lines.append("")
            lines.append("\t-- Defined constants")
            for define in self.defines:
                # Skip invalid identifiers
                if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', define.name):
                    continue
                lines.append(f"\t{define.name} = {to_hex(define.value)},")

        lines.append("}")
        lines.append("")
        lines.append("return constants")

        return '\n'.join(lines)
    
    def generate_init_file(self, lib_name: str, dll_path: str = "./") -> str:
        """Generate the init.luau file"""
        lines = [
            "--!strict",
            "--!optimize 2",
            "-- Made by FFIGen (Kinemium)",
            "",
            f'local dll = "{dll_path}"',
            "local ffi = zune.ffi",
            "local platform = zune.platform",
            "",
            "local structs = require(\"./structs\")",
            "local funcs = require(\"./funcs\")",
            "local constants = require(\"./constants\")",
            "",
            "local libname",
            'if platform.os == "windows" then',
            f'\tlibname = "{lib_name}.dll"',
            'elseif platform.os == "linux" then',
            f'\tlibname = "{lib_name}.so"',
            'elseif platform.os == "macos" then',
            f'\tlibname = "{lib_name}.dylib"',
            "end",
            "",
            f"local {lib_name}: funcs.Fns = ffi.dlopen(dll .. libname, funcs)",
            "",
            "return {",
            f"\tlib = {lib_name},",
            "\tstructs = structs,",
            "\tconstants = constants,",
            "}",
        ]
        
        return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Luau FFI bindings from C header files',
        epilog='''
Examples:
  # From local files
  python c_to_luau_ffi.py raylib.h --lib-name raylib
  
  # From GitHub repository
  python c_to_luau_ffi.py --github https://github.com/raysan5/raylib --lib-name raylib
  
  # From GitHub with specific branch and path
  python c_to_luau_ffi.py --github https://github.com/raysan5/raylib/tree/master/src --lib-name raylib
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Input source (either local files or GitHub)
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument('headers', nargs='*', type=Path, 
                            help='Input C header file(s)')
    input_group.add_argument('--github', type=str,
                            help='GitHub repository URL (e.g., https://github.com/user/repo)')
    
    parser.add_argument('--include-dir', default='include',
                      help='Subdirectory to fetch from GitHub (default: include)')
    parser.add_argument('--output-dir', type=Path, default=Path('./bindings'),
                      help='Output directory for generated files')
    parser.add_argument('--lib-name', required=True,
                       help='Name of the library (without extension)')
    parser.add_argument('--dll-path', default='./',
                       help='Path to DLL/SO files (default: ./)')
    parser.add_argument('--fields-per-line', type=int, default=4,
                       help='Number of struct fields per line (default: 4)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--skip', type=str,
                       help='Comma-separated list of parts to skip: funcs,structs,constants,init')
    parser.add_argument('--include-pattern', type=str,
                       help='Regex pattern for header files to include')
    parser.add_argument('--exclude-pattern', type=str,
                       help='Regex pattern for header files to exclude')
    
    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Parse skip list
    skip_parts = set()
    if args.skip:
        skip_parts = set(p.strip().lower() for p in args.skip.split(','))
    
    # Determine input source
    temp_dir = None
    header_files = list(Path('.').rglob('*.h'))
    if not header_files:
        print("No header files found in the current directory or subdirectories.")
        return
    
    try:
        if args.github:
            temp_dir = GitHubFetcher.fetch_headers_from_github(args.github, args.include_dir)
            header_files = list(temp_dir.rglob('*.h'))
            if not header_files:
                print("Error: No header files found in the fetched directory")
                return 1
        else:
            if args.headers:
                header_files = args.headers
            else:
                # No headers provided, grab all in current directory recursively
                header_files = list(Path('.').rglob('*.h'))
                if not header_files:
                    print("Error: No header files found in the current directory or subdirectories")
                    return 1

        # Filter header files based on patterns
        if args.include_pattern:
            import re as re_module
            include_re = re_module.compile(args.include_pattern)
            header_files = [h for h in header_files if include_re.search(str(h))]

        if args.exclude_pattern:
            import re as re_module
            exclude_re = re_module.compile(args.exclude_pattern)
            header_files = [h for h in header_files if not exclude_re.search(str(h))]

        if not header_files:
            print("Error: No header files match the specified patterns")
            return 1

        # Parse all header files
        generator = CToLuauFFI()
        
        for header in header_files:
            if not header.exists():
                print(f"Warning: {header} does not exist, skipping...")
                continue
            
            print(f"Parsing {header.name}...")
            generator.parse_header(header)
        
        if args.verbose:
            print(f"\nTotal found across all headers:")
            print(f"  {len(generator.structs)} structs")
            print(f"  {len(generator.functions)} functions")
            print(f"  {len(generator.enums)} enums")
            print(f"  {len(generator.defines)} defines")

        # Generate files
        print("\nGenerating bindings...")

        if 'structs' not in skip_parts:
            structs_content = generator.generate_structs_file(args.fields_per_line)
            (args.output_dir / 'structs.luau').write_text(structs_content)
            print(f"  OK {args.output_dir / 'structs.luau'}")

        if 'funcs' not in skip_parts:
            funcs_content = generator.generate_funcs_file()
            (args.output_dir / 'funcs.luau').write_text(funcs_content)
            print(f"  OK {args.output_dir / 'funcs.luau'}")

        if 'constants' not in skip_parts:
            constants_content = generator.generate_constants_file()
            (args.output_dir / 'constants.luau').write_text(constants_content)
            print(f"  OK {args.output_dir / 'constants.luau'}")

        if 'init' not in skip_parts:
            init_content = generator.generate_init_file(args.lib_name, args.dll_path)
            (args.output_dir / 'init.luau').write_text(init_content)
            print(f"  OK {args.output_dir / 'init.luau'}")

        print("\nBindings generated successfully!")
        
        if args.github:
            print(f"\nFetched from: {args.github}")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        # Clean up temporary directory if it was created
        if temp_dir and temp_dir.exists():
            print(f"\nCleaning up temporary files...")
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    exit(main())
