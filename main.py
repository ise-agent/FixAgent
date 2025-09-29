import json
import io
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stdout

from langgraph.errors import GraphRecursionError
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage


from prompt import locator_template, suggester_template, fixer_template
from workflow.graph import create_workflow
from router.router import is_tool_result_message
from utils.logging import set_api_stats_file
from utils.logger import Logger
from settings import settings

MODEL_TYPE = settings.openai_model or "claude-sonnet-4-20250514"
ROUND = settings.round

# Use settings for project configuration
TEST_BED = settings.test_bed
PROJECT_NAME = settings.project_name
INSTANCE_ID = settings.instance_id
PROBLEM_STATEMENT = settings.problem_statement

# No external dependencies needed - using internal Logger

# Initialize LLM
# TODO @<hanyu44> 修改配置
llm = ChatOpenAI(
    model=MODEL_TYPE,
    temperature=0.0,
    api_key="sk-NdZukOuQQRhydvPW33Dc1e05AbCa4fE394BfD3FfB9Ac09Be",
    base_url=settings.openai_base_url,
)

# Setup logging
base_dir = TEST_BED
project_name = PROJECT_NAME
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
logs_dir = Path(__file__).parent / "logs"
logger = Logger(logs_dir / ROUND, f"{INSTANCE_ID}_{timestamp}.log")
res_dir = logs_dir / ROUND / f"{INSTANCE_ID}_{timestamp}.json"
res_json = {"location": [], "failed_patch": []}
api_stats_file = logs_dir / ROUND / f"{INSTANCE_ID}_{timestamp}_api_stats.json"
set_api_stats_file(str(api_stats_file))


def get_default_tools():
    """Get default tools"""
    from tools.retriever_tools import (
        browse_project_structure,
        get_all_classes_and_methods,
        search_for_file_by_keyword_in_neo4j,
        get_relevant_entities,
        search_method_fuzzy,
        search_method_accurately,
        search_constructor_in_class,
        search_field_variables_of_class,
        extract_imports,
        search_variable_by_name,
        search_variable_by_only_name,
        search_test_cases_by_method,
        read_file_lines,
        search_keyword_with_context,
        execute_shell_command_with_validation,
    )

    return [
        browse_project_structure,
        get_all_classes_and_methods,
        search_for_file_by_keyword_in_neo4j,
        get_relevant_entities,
        search_method_fuzzy,
        search_method_accurately,
        search_constructor_in_class,
        search_field_variables_of_class,
        extract_imports,
        search_variable_by_name,
        search_variable_by_only_name,
        search_test_cases_by_method,
        read_file_lines,
        search_keyword_with_context,
        execute_shell_command_with_validation,
    ]


def main():
    print("Starting ISEA")
    print(f"Model: {MODEL_TYPE}")
    print(f"Project: {project_name}")
    print(f"Base directory: {base_dir}")
    print("-" * 60)

    # Get tools
    locator_tools = get_default_tools()
    suggester_tools = get_default_tools()
    fixer_tools = get_default_tools()

    # Create workflow
    try:
        workflow = create_workflow(
            llm=llm,
            locator_tools=locator_tools,
            suggester_tools=suggester_tools,
            fixer_tools=fixer_tools,
            locator_template=locator_template,
            suggester_template=suggester_template,
            fixer_template=fixer_template,
            base_dir=base_dir,
            project_name=project_name,
        )

        graph = workflow.compile()
        print("Workflow created successfully")

    except Exception as e:
        print(f"Failed to create workflow: {e}")
        return

    # Initialize state
    initial_state = {
        "messages": [
            HumanMessage(content="Try to find and repair the bug in the project.")
        ],
        "initial_failure": None,
        "location": None,
        "locations": None,
        "suggestion": "",
        "suggest_count": 0,
        "fix_count": 0,
        "patch": "",
        "ready_to_locate": False,
        "ready_to_fix": False,
        "summary": "",
        "invoker": "",
        "next": "Locator",
        "failed_location": [],
        "update_num": 1,
        "location_content": "",
        "problem_statement": PROBLEM_STATEMENT,
    }

    # Run the workflow
    try:
        print("Starting workflow execution...")
        events = graph.stream(initial_state, {"recursion_limit": 150})

        for s in events:
            for a in s:
                if "messages" in s[a].keys():
                    results = ""
                    if len(s[a]["messages"]) == 0:
                        s[a]["messages"] = [""]
                    if "update_num" in s[a].keys():
                        messages = s[a]["messages"][s[a]["update_num"] * (-1) :]
                    else:
                        messages = s[a]["messages"][-1:]

                    for message in messages:
                        if isinstance(message, tuple):
                            results += str(message)
                        else:
                            with io.StringIO() as buf, redirect_stdout(buf):
                                if message != "":
                                    if is_tool_result_message(message):
                                        print(f"   {message.content}")
                                    else:
                                        message.pretty_print()
                                else:
                                    print("=" * 32 + " Summarize " + "=" * 32)
                                results += buf.getvalue()

                    logger.log("info", results + "\n")

                    # Also print to console for real-time feedback
                    if results.strip():
                        print(results)

    except GraphRecursionError:
        logger.log("info", "Recursion limit reached. Performing final actions...")
        if "succeed_patch" not in res_json.keys():
            with open(res_dir, "w", encoding="utf-8") as f:
                json.dump(res_json, f, indent=4)
            logger.log("info", f"Patch info saved to {res_dir} successfully!")

    except Exception as e:
        print(f"Error during workflow execution: {e}")
        logger.log("error", f"Workflow execution failed: {e}")

    finally:
        print(f"\nResults saved to: {res_dir}")
        print(f"Logs saved to: {logs_dir / ROUND}")
        print("ISEA execution completed")


if __name__ == "__main__":
    main()
