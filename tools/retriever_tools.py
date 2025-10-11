"""Tool functions that wrap CKGRetriever methods for agent use"""
import os
import re
from typing import Optional
from pathlib import Path

from retriever.ckg_retriever import CKGRetriever
from settings import settings
from langchain_core.tools import tool
import subprocess
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# Global retriever instance (will be initialized when first used)
_retriever: Optional[CKGRetriever] = None


def get_retriever() -> CKGRetriever:
    """Get or create the global CKGRetriever instance (memory-based)"""
    global _retriever
    if _retriever is None:
        # 构建内存版知识图谱
        from kg.main import build_knowledge_graph
        dir_name = Path(settings.TEST_BED) / settings.PROJECT_NAME
        print(f"Building knowledge graph for {dir_name}...")
        _retriever = build_knowledge_graph(dir_name)
    return _retriever

graph_retriever = get_retriever()

def truncate_output(text: str, max_chars: int = 5000) -> str:
    """
    Truncate text output if it exceeds max_chars limit
    """
    if isinstance(text, (list, dict)):
        text = str(text)
    
    if len(text) <= max_chars:
        return text
    
    truncated = text[:max_chars]
    return f"{truncated}\n\n... [输出被截断，原始长度: {len(text)} 字符，显示前 {max_chars} 字符]"

@tool
def extract_complete_method(file, full_qualified_name):
    '''
    Extract method implementation and automatically analyze its relationships with other code.
    Returns both the complete method body and its connections to other methods, classes, and variables.
    :param file: The file to search for method.
    :param full_qualified_name: The full_qualified_name of the target method.
    :return: A Dict containing method implementation and relationship analysis.
    '''
    # Get method implementation
    res = graph_retriever.search_method_accurately(file, full_qualified_name)
    if res is None:
        return "Method not found! Please check your parameters and try again."

    method_res = []
    for method in res:
        # Add line numbers to method content
        lines = method.content.split('\n')
        numbered_content = '\n'.join(f"{method.start_line + i:4d}: {line}" for i, line in enumerate(lines))

        method_info = {
            "content": numbered_content,
            "start_line": method.start_line,
            "end_line": method.end_line
        }

        # Automatically get relationships for this method
        try:
            relationships = graph_retriever.get_relevant_entities(file, full_qualified_name)
            if relationships:
                method_info["analysis_header"] = "=== CODE RELATIONSHIPS ANALYSIS ==="
                method_info["relationships"] = relationships
        except Exception as e:
            method_info["relationships_note"] = f"Could not retrieve relationships: {str(e)}"

        method_res.append(method_info)

    if len(method_res) == 0:
        method_res.append("Check whether your full_qualified_name is named in compliance with the specification.")
    return method_res
@tool
def find_methods_by_name(name: str):
    '''
    Find all methods with a specific name across the project and analyze their relationships.
    Returns method implementations with automatic relationship analysis for better understanding.
    :param name: method's name.
    :return: A List containing method info with relationship analysis.
    '''

    res = graph_retriever.search_method_fuzzy(name)
    if res is None:
        return "Method not found! Please check your parameters and try again."

    method_res = []
    for method in res:
        # Add line numbers to method content
        lines = method.content.split('\n')
        numbered_content = '\n'.join(f"{method.start_line + i:4d}: {line}" for i, line in enumerate(lines))

        method_info = {
            "absolute_path": method.absolute_path,
            "full_qualified_name": method.full_qualified_name,
            "content": numbered_content,
            "start_line": method.start_line,
            "end_line": method.end_line
        }

        # Automatically get simplified relationships for each method
        try:
            relationships = graph_retriever.get_relevant_entities(method.absolute_path, method.full_qualified_name)
            if relationships:
                # Only include key relationship info, not full details
                simplified_relationships = {}
                for rel_type, entities in relationships.items():
                    if entities:  # Only include non-empty relationships
                        # Just show entity names and paths, not full content
                        simplified_entities = []
                        for entity in entities:  # Limit to first 3 entities per relationship type
                            simple_entity = {
                                "name": entity.get("name", ""),
                                "full_qualified_name": entity.get("full_qualified_name", ""),
                                "absolute_path": entity.get("absolute_path", "")
                            }
                            simplified_entities.append(simple_entity)


                        simplified_relationships[rel_type] = simplified_entities

                if simplified_relationships:
                    method_info["analysis_header"] = "=== KEY RELATIONSHIPS (simplified) ==="
                    method_info["relationships"] = simplified_relationships
        except Exception as e:
            method_info["relationships_note"] = f"Could not retrieve relationships: {str(e)}"

        method_res.append(method_info)

    if len(method_res) == 0:
        method_res.append("you're searching for could be a variable name, or the function might not be explicitly defined in the visible scope but still exists elsewhere.")

    # Apply character limit
    result_str = str(method_res)
    return truncate_output(result_str)
    
# @tool
# def search_for_file_by_keyword(root, keyword, max_results=15):
#     '''
#     Recursively searches through the root directory and return those files'content containing the keyword.
#     :param root: The root directory to start the search.
#     :param keyword: The keyword in file to search for.
#     :return: A list of python files containing the keyword.
#     '''
#     exclude_dirs=None
#     if exclude_dirs is None:
#         exclude_dirs = {'reproduction', 'VUL4J'}

#     matching_files = []

#     for dirpath, dirnames, filenames in os.walk(root):
#         dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
#         for fname in filenames:
#             if not fname.endswith('.py'):
#                 continue

#             full_path = os.path.join(dirpath, fname)
#             name_match = keyword.lower() in fname.lower()
#             content_match = False
#             try:
#                 with open(full_path, 'r', encoding='utf-8') as f:
#                     content = f.read()
#                 content_match = keyword.lower() in content.lower()
#             except Exception as e:
#                 print(f"Error reading {full_path}: {e}")

#             if name_match or content_match:
#                 matching_files.append(full_path)

#     if len(matching_files) > max_results:
#         # 优先文件名匹配
#         priority = [f for f in matching_files if keyword.lower() in os.path.basename(f).lower()]
#         others = [f for f in matching_files if f not in priority]

#         result = priority[:max_results]
#         needed = max_results - len(result)
#         if needed > 0:
#             result.extend(others[:needed])
#         return result

#     return matching_files

@tool
def get_code_relationships(file, full_qualified_name):
    '''
    The prerequisite for using it is to know the absolute path and the full_qualified_name of this entity.
    The function's role is to find references to an entity, as well as , belongs_to ,calls, has_method,has_variable, or inherits, and return the nodes involved in these relationships.
    :param file: The file to search for method.
    :param full_qualified_name: The full_qualified_name of the target method(<Class.Method> such as: BClass.call_func1).
    :return:  A Dict including keys:
        BELONGS_TO
        CALLS
        HAS_METHOD
        HAS_VARIABLE
        INHERITS
        REFERENCES
    '''
    res = graph_retriever.get_relevant_entities(file,full_qualified_name)
    return res

@tool
def analyze_file_structure(file):
    '''
    Searches through a python file instead of a dir and return all the classes and method information.
    :param file: The path to the python file.
    :return: A string consisting of class and method information.
        including class : name ,absolute_path
        including method : name , full_qualified_name , params
    '''
    # if not os.path.exists(file):
    #     return f"No such file or directory of {file}"
    classes, methods = graph_retriever.read_all_classes_and_methods(file)
    res = "Each line below indicates a class, including class_name and absolute_path:\n"
    res += "\n".join(f"{i.name} {i.absolute_path}" for i in classes)
    res += "\nEach line below indicates a method, including method_name, full_qualifie_ name and param list:\n"
    for method in methods:
        res += f"{method.name}  {method.full_qualified_name}  {method.params}\n"

    if not classes and not methods:
        res += "\n\nNo class or method information found. Please double-check the file path or consider using the `browse_project_structure` tool to verify the structure."
    
    return truncate_output(res)

@tool
def find_class_constructor(class_name: str):
    '''
    according to class's name
    searching for a python class and return its constructor method information.
    :param class_name: The name of the class.
    :return: A string of the construction method content.
    '''
    res = graph_retriever.search_constructor_in_clazz(class_name)
    res_str = ""
    for method in res:
        # Add line numbers to method content
        lines = method.content.split('\n')
        numbered_content = '\n'.join(f"{method.start_line + i:4d}: {line}" for i, line in enumerate(lines))
        
        res_str += f"Method:\n{numbered_content}\nstart line: {method.start_line}\nend line: {method.end_line}"
    return res_str


@tool
def find_variable_usage(file: str,variable_name: str, ):
    '''
        Searches through the knowledge graph and return variables of certain name in the given file.

        :param file: path of the file
        :param variable_name: name of the variable to search
        :return: a string of variable info.
    '''
    res = graph_retriever.search_variable_query(file, variable_name)
    res_str = ""
    for v in res:
        # Add line numbers to variable content if it spans multiple lines
        lines = v.content.split('\n')
        if len(lines) > 1 and v.start_line:
            numbered_content = '\n'.join(f"{v.start_line + i:4d}: {line}" for i, line in enumerate(lines))
            res_str += f"abs_path:{v.absolute_path}\ncontent:\n{numbered_content}\nstart line:{v.start_line}\nend line:{v.end_line}\n\n"
        else:
            res_str += f"abs_path:{v.absolute_path}\ncontent:{v.content}\nstart line:{v.start_line}\nend line:{v.end_line}\n\n"
    return res_str if res_str != "" else "No variable found.The variable might be in the __init__ function or it might be a method or a class name."



@tool
def list_class_attributes(class_name: str) -> str:
    """
        Searches through the knowledge graph and return field variables info of the class given, including name, data type and content.

        :param class_name: Name of the class to search for
        :return: a string of variable info.
        """
    if '.' in class_name:
        class_name = class_name.split('.')[-1]
    res = graph_retriever.search_field_variables_of_class(class_name)
    res_str = ""
    if len(res) == 0:
        return "No field variable found!"
    res_str += f"Each line below indicates a variable inside the class {class_name}, including its name, full qualified name, data type and content\n"
    for variable in res:
        res_str += f"{variable.name}  {variable.full_qualified_name}  {variable.data_type}  {variable.content}\n"
    return res_str


@tool
def show_file_imports(python_file_path):
    """
        Get all import information of the given Python file.

        :param python_file_path: The path to the Python file
        :return: Import lines inside the Python file
    """
    try:
        with open(python_file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        import_pattern = r'^\s*(?:import|from)\s+.*?(?:;|\n)'
        imports = re.findall(import_pattern, content, re.MULTILINE)

        return imports
    except FileNotFoundError:
        print(f"Error:file {python_file_path} not found。")
        return []
    except Exception as e:
        print(f"Uknown error:{e}")
        return []
@tool
def find_files_containing(keyword):
    """
    Searches through the knowledge graph and return those files'content containing the keyword.

    :param keyword: The keyword in file to search for.
    :return: A list of python files (containing the keyword.) and keyword's full qualified name 
    """
    res = graph_retriever.search_file_by_keyword(keyword)
    if len(res) == 0:
        return ["No file containing keyword"]
    return res

@tool
def find_all_variables_named(variable_name: str) -> str:
    """
    Searches through the knowledge graph for all variables matching the given name.

    :param variable_name: name (or part of the fully‐qualified name) of the variable to search for
    :return: a formatted string of all matching variable nodes, or "No variable found."
    """
    res = graph_retriever.search_variable_by_only_name_query(variable_name)
    if not res:
        return "No variable found. It might be a method or a class name."
    
    out = []
    for v in res:
        # Add line numbers to variable content if it spans multiple lines
        lines = v.content.split('\n')
        if len(lines) > 1 and v.start_line:
            numbered_content = '\n'.join(f"{v.start_line + i:4d}: {line}" for i, line in enumerate(lines))
            content_display = f"content:\n{numbered_content}"
        else:
            content_display = f"content: {v.content}"
            
        out.append(
            f"abs_path: {v.absolute_path}\n"
            f"name: {v.name}\n"
            f"full_qualified_name: {v.full_qualified_name}\n"
            f"{content_display}\n"
            f"start line: {v.start_line}\n"
            f"end line: {v.end_line}\n"
        )
    
    result = "\n".join(out)
    return truncate_output(result)

# @tool
# def search_test_cases_by_method(full_qualified_name: str) -> str:
#     """
#     Searches through the knowledge graph for all test‐case nodes that the given method tests.

#     :param full_qualified_name: the fully‐qualified name of the method under test
#     :return: a formatted string of all test case nodes reached by a TESTED relationship,
#              or "No test case found." if none.
#     """
    
#     test_cases = graph_retriever.search_test_cases_by_method_query(full_qualified_name)
#     if not test_cases:
#         return "No test function was found; it is possible that this function has not been tested yet."
    
#     lines = []
#     for tc in test_cases:
#         # Add line numbers to test case content
#         content_lines = tc.content.split('\n')
#         numbered_content = '\n'.join(f"{tc.start_line + i:4d}: {line}" for i, line in enumerate(content_lines))
        
#         lines.append(
#             f"abs_path: {tc.absolute_path}\n"
#             f"name: {tc.name}\n"
#             f"content:\n{numbered_content}\n"
#             f"start line: {tc.start_line}\n"
#             f"end line: {tc.end_line}\n"
#         )
    
#     result = "\n".join(lines)
#     return truncate_output(result)

def _browse_structure(
    dir_path: str,
    prefix: str = ''
) -> str:
    """
    Recursive logic to generate a tree representation, ignoring .git directories.
    """
    if not os.path.exists(dir_path):
        raise FileNotFoundError(f"Directory \"{dir_path}\" does not exist.")
    tree_str = ''
    entries = sorted(e for e in os.listdir(dir_path) if e != '.git')
    total = len(entries)
    for idx, entry in enumerate(entries, start=1):
        path = os.path.join(dir_path, entry)
        connector = '└── ' if idx == total else '├── '
        tree_str += f"{prefix}{connector}{entry}\n"
        if os.path.isdir(path):
            extension = '    ' if idx == total else '│   '
            tree_str += _browse_structure(path, prefix + extension)
    return tree_str

# Exposed tool entrypoint
# @tool
# def browse_project_structure(
#     dir_path: str,
#     prefix: str = ''
# ) -> str:
#     """
#     Generate a tree representation of the directory at dir_path, ignoring .git directories.

#     :param dir_path: Path to the root directory
#     :param prefix: Internal use for line prefixing
#     :return: A string representing the directory tree
#     """
#     return _browse_structure(dir_path, prefix)

@tool
def explore_directory(
    dir_path: str,
    prefix: str = ''
) -> str:
    """
    Generate a simple listing of the immediate contents of dir_path (one level only), ignoring .git directories.

    :param dir_path: Path to the root directory
    :param prefix: Internal use for line prefixing (not used in single-level mode)
    :return: A string representing the directory contents
    """
    if not os.path.exists(dir_path):
        return f"Directory \"{dir_path}\" does not exist."

    try:
        entries = sorted(e for e in os.listdir(dir_path) if e != '.git')
        if not entries:
            return f"Directory \"{dir_path}\" is empty."

        result = f"Contents of {dir_path}:\n"
        for entry in entries:
            path = os.path.join(dir_path, entry)
            if os.path.isdir(path):
                result += f"{entry}/\n"
            else:
                result += f"{entry}\n"
        return result
    except PermissionError:
        return f"Permission denied accessing directory \"{dir_path}\"."
    except Exception as e:
        return f"Error reading directory \"{dir_path}\": {str(e)}"

@tool
def read_file_lines(
    file_path: str,
    start_line: int,
    end_line: int
) -> str:
    """
    Read specified line range from a file, automatically adjusting line numbers to ensure
    they don't exceed maximum lines or 50-line limit.

    :param file_path: Absolute path to the file
    :param start_line: Starting line number (1-based)
    :param end_line: Ending line number
    :return: Formatted string containing file info and content
    """
    # Adjust start line (ensure it's at least 1)
    adjusted_start = max(1, start_line)
    adjusted_end = end_line
    total_lines = 0
    content_lines = []

    try:
        # First pass: count total lines in file
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for total_lines, _ in enumerate(f, 1):
                pass

        # Handle invalid line range
        if total_lines == 0 or adjusted_start > total_lines:
            return f"File: {file_path}\nTotal lines: {total_lines}\nError: Invalid line range"

        # Adjust end line (ensure it doesn't exceed max lines or 50-line limit)
        adjusted_end = min(
            max(adjusted_start, adjusted_end),  # Ensure end >= start
            adjusted_start + 50 - 1,          # Read max 50 lines
            total_lines                        # Don't exceed file end
        )

        # Second pass: read the specified line range with line numbers
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for current_line, line in enumerate(f, 1):
                if current_line < adjusted_start:
                    continue
                if current_line > adjusted_end:
                    break
                # Add line numbers to content
                content_lines.append(f"{current_line:4d}: {line}")

        content = ''.join(content_lines)
        result = f"File: {file_path}\nTotal lines: {total_lines}\nShowing lines {adjusted_start}-{adjusted_end}:\n\n{content}"
        return truncate_output(result)

    except Exception as e:
        return f"File: {file_path}\nError reading file: {str(e)}"

@tool
def search_code_with_context(keyword: str, search_path: str) -> str:
    """
    Search for lines containing the keyword in Python files, supporting both directory and file paths.
    Returns the content of 3 lines before and after (including the matched line),
    along with the file path and start/end line numbers.

    :param keyword: The keyword to search for.
    :param search_path: The directory or file path to search in.
    :return: A formatted string of search results.
    """
    results = []

    def search_in_file(file_path: str):
        """Helper function to search for keyword in a single file"""
        if not file_path.endswith('.py'):
            return
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            for idx, line in enumerate(lines):
                if keyword in line:
                    start = max(0, idx - 3)
                    end = min(len(lines), idx + 4)  # idx+4 because end is exclusive
                    # Add line numbers to context
                    context_lines = []
                    for i in range(start, end):
                        context_lines.append(f"{i + 1:4d}: {lines[i]}")
                    context = ''.join(context_lines)

                    results.append({
                        file_path: {
                            "start_line": start + 1,
                            "end_line": end,
                            "content": context
                        }
                    })

                    # Limit to first 15 matches to prevent excessive output
                    if len(results) >= 15:
                        return True  # Signal to break outer loops
        except Exception:
            pass
        return False

    # Check if search_path is a file or directory
    if os.path.isfile(search_path):
        # Single file search
        search_in_file(search_path)
    elif os.path.isdir(search_path):
        # Directory search - walk through all files
        for dirpath, _, filenames in os.walk(search_path):
            for fname in filenames:
                if not fname.endswith('.py'):
                    continue
                file_path = os.path.join(dirpath, fname)
                if search_in_file(file_path):
                    break  # Break if we hit the limit

            # Break outer loop if we have enough results
            if len(results) >= 15:
                break
    else:
        return f"Path '{search_path}' does not exist or is not accessible."

    # Format results as string
    if not results:
        path_type = "file" if os.path.isfile(search_path) else "directory"
        return f"No matches found for '{keyword}' in {path_type} '{search_path}'"

    path_type = "file" if os.path.isfile(search_path) else "directory"
    result_str = f"Search results for '{keyword}' in {path_type} (showing first {len(results)} matches):\n\n"
    for result_dict in results:
        for file_path, content_info in result_dict.items():
            result_str += f"File: {file_path}\n"
            result_str += f"Lines {content_info['start_line']}-{content_info['end_line']}:\n"
            result_str += f"{content_info['content']}\n"
            result_str += "="*80 + "\n\n"

    return truncate_output(result_str)

@tool
def execute_shell_command_with_validation(command: str, working_directory: str = None) -> str:
    """
    Execute a shell command after validation by a small model for safety.
    The LLM generates the command, then a validation model checks it before execution.

    :param command: The shell command to execute
    :param working_directory: Optional working directory to execute the command in
    :return: Command output including stdout, stderr, and return code
    """


    # Validation prompt for the small model
    validation_prompt = f"""You are a security validator for shell commands.
CRITICAL: NO FILE MODIFICATIONS ARE ALLOWED 

Analyze this command for safety and determine if it should be executed:

Command: {command}
Working Directory: {working_directory or 'current directory'}

Classification Rules:
- SAFE: ONLY read-only operations (ls, cat, head, tail, grep, find, ps, top, df, du, wc, file, stat, etc.)
- UNSAFE: ANY file modifications, writes, execute, deletions, moves, copies, permission changes, system modifications, network operations, privilege escalation

STRICTLY FORBIDDEN:
- File creation/modification: touch, echo >, >>, tee, nano, vim, etc.
- File operations: rm, mv, cp, mkdir, rmdir, chmod, chown, etc.
- System changes: sudo, su, systemctl, service, kill, mount, etc.
- Package management: apt, yum, pip install, npm install, etc.
- Network operations: wget, curl, ssh, scp, etc.

Respond with exactly one word: "SAFE" or "UNSAFE"

If UNSAFE, briefly explain why in one sentence after the classification."""

    try:
        # Initialize small validation model (using faster/cheaper model)
        validator = ChatOpenAI(
            model="gpt-4o-mini",  # Using faster model for validation
            temperature=0.0,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        # Get validation result
        validation_response = validator.invoke([HumanMessage(content=validation_prompt)])
        validation_result = validation_response.content.strip()

        # Check if command is safe
        if not validation_result.startswith("SAFE"):
            return f"Command blocked by safety validation: {validation_result}"

        # Set working directory if provided and exists
        cwd = working_directory if working_directory and os.path.exists(working_directory) else None

        # Execute command with timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout
            cwd=cwd
        )

        output_lines = []
        output_lines.append(f"Command validated and executed: {command}")
        if cwd:
            output_lines.append(f"Working directory: {cwd}")
        output_lines.append(f"Return code: {result.returncode}")

        if result.stdout:
            output_lines.append("STDOUT:")
            output_lines.append(result.stdout)

        if result.stderr:
            output_lines.append("STDERR:")
            output_lines.append(result.stderr)

        if not result.stdout and not result.stderr:
            output_lines.append("No output")

        output = "\n".join(output_lines)
        return truncate_output(output)

    except subprocess.TimeoutExpired:
        return f"Command '{command}' timed out after 30 seconds"
    except Exception as e:
        return f"Error executing command '{command}': {str(e)}"

if __name__ == "__main__":
    # Example usage

    print(search_code_with_context("_split_gcd", "/root/hy/projects/sympy/sympy/simplify"))