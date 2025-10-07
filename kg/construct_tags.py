import os
import warnings
import json
import ast
import inspect
import builtins
from pathlib import Path
from collections import namedtuple
import chardet
from tqdm import tqdm
from pygments.lexers import guess_lexer_for_filename
from pygments.token import Token
from pygments.util import ClassNotFound
from tree_sitter_languages import get_language, get_parser
from grep_ast import filename_to_lang

from utils import create_structure

# Suppress tree-sitter future warnings
warnings.simplefilter("ignore", category=FutureWarning)

# Tag tuple for storing code tags
Tag = namedtuple("Tag", "rel_fname fname line name kind category info")

class CodeGraph:
    def __init__(self, root=None):
        if not root:
            root = os.getcwd()
        self.root = root

        # Build repository structure and dump to kg.json
        self.structure = create_structure(self.root)
        kg_path = Path(__file__).resolve().parent / "kg.json"
        with open(kg_path, 'w', encoding='utf-8') as f:
            json.dump(self.structure, f, indent=4)

        # Ensure structure is wrapped under root folder name
        if not isinstance(self.structure, dict) or os.path.basename(self.root) not in self.structure:
            self.structure = {os.path.basename(self.root): self.structure}

    def get_rel_fname(self, fname):
        return os.path.relpath(fname, self.root)

    def get_mtime(self, fname):
        try:
            return os.path.getmtime(fname)
        except FileNotFoundError:
            return None

    def std_proj_funcs(self, code, fname):
        std_funcs, std_libs = [], []
        tree = ast.parse(code)
        lines = code.split('\n')

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                stmt = lines[node.lineno - 1].strip()
                try:
                    exec(stmt)
                except Exception:
                    continue
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [alias.name for alias in node.names]

                for name in names:
                    std_libs.append(name)
                    member = name if name not in builtins.__dict__ else builtins
                    std_funcs.extend([n for n, m in inspect.getmembers(eval(member)) if callable(m)])

        return std_funcs, std_libs

    def get_tags(self, fname, rel_fname):
        if self.get_mtime(fname) is None:
            return []
        return list(self.get_tags_raw(fname, rel_fname))

    def get_tags_raw(self, fname, rel_fname):
        # Load structure info for this file
        parts = rel_fname.split(os.sep)
        subtree = self.structure.get(os.path.basename(self.root), {})
        for part in parts:
            subtree = subtree.get(part, {}) if isinstance(subtree, dict) else {}

        # Read code with encoding detection
        with open(fname, 'rb') as f:
            raw = f.read()
        try:
            code = raw.decode('utf-8')
        except UnicodeDecodeError:
            # 检测编码并解码，失败字节替换
            detect = chardet.detect(raw)
            enc = detect.get('encoding') or 'latin-1'
            code = raw.decode(enc, errors='replace')

        lines = code.splitlines()

        # Parse with tree-sitter
        lang = filename_to_lang(fname)
        if not lang:
            return
        parser = get_parser(lang)
        tree = parser.parse(code.encode('utf-8'))

        # AST fallback for source info
        try:
            tree_ast = ast.parse(code)
        except Exception:
            tree_ast = None

        # Filter standard library functions
        try:
            std_funcs, std_libs = self.std_proj_funcs(code, fname)
        except Exception:
            std_funcs, std_libs = [], []

        # Capture definitions and references
        query = get_language(lang).query("""
            (class_definition name: (identifier) @name.definition.class)
            (function_definition name: (identifier) @name.definition.function)
            (call function: [(identifier) @name.reference.call
                              (attribute attribute: (identifier) @name.reference.call)])
        """)
        captures = query.captures(tree.root_node)

        saw = set()
        for node, tag in captures:
            kind = 'def' if 'definition' in tag else 'ref'
            saw.add(kind)
            name = node.text.decode('utf-8')
            if name in std_funcs or name in std_libs or name in dir(builtins):
                continue

            category = 'class' if 'class ' in lines[node.start_point[0]] else 'function'
            info = ''
            line_nums = [node.start_point[0], node.end_point[0]]

            yield Tag(rel_fname, fname, line_nums, name, kind, category, info)

        # Fallback: if no definitions found but refs exist, or vice versa, skip
        if 'ref' in saw or 'def' not in saw:
            return

        # Pygments fallback to capture tokens
        try:
            lexer = guess_lexer_for_filename(fname, code)
        except ClassNotFound:
            return

        tokens = [t[1] for t in lexer.get_tokens(code) if t[0] in Token.Name]
        for name in tokens:
            yield Tag(rel_fname, fname, -1, name, 'ref', 'function', '')

    def find_src_files(self, directory):
        files = []
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith('.py'):
                files.append(entry.path)
            elif entry.is_dir():
                files.extend(self.find_src_files(entry.path))
        return files

    def find_files(self, paths):
        py_files = []
        for path in paths:
            if os.path.isdir(path):
                py_files.extend(self.find_src_files(path))
            elif path.endswith('.py'):
                py_files.append(path)
        return py_files


def run(dir_name: str):
    cg = CodeGraph(root=dir_name)
    py_files = cg.find_files([dir_name])

    def collect_tags(fname):
        rel = cg.get_rel_fname(fname)
        return cg.get_tags(fname, rel)

    all_tags = []
    for f in tqdm(py_files, desc="Processing files one by one"):
        try:
            tags = collect_tags(f)
            all_tags.extend(tags)
        except Exception as e:
            print(f"Error on {f}: {e}")

    out_path = Path(__file__).resolve().parent / "tags.json"
    if out_path.exists():
        out_path.unlink()
    with open(out_path, 'w', encoding='utf-8') as f:
        for tag in all_tags:
            json.dump({
                'fname': tag.fname,
                'rel_fname': tag.rel_fname,
                'line': tag.line,
                'name': tag.name,
                'kind': tag.kind,
                'category': tag.category,
                'info': tag.info,
            }, f, ensure_ascii=False)
            f.write('\n')
    print(f"🚀 Successfully generated kg.json and tags.json in {Path(dir_name).resolve()}")

if __name__ == '__main__':
    import sys
    run(sys.argv[1])
