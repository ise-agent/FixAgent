"""Core agent functionality"""
import json
import re
import uuid

from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
    AIMessage,
)
from langchain_core.prompts import ChatPromptTemplate

from agent.state import AgentState


def create_agent(llm, tools, prompt: ChatPromptTemplate, base_dir: str, project_name: str):
    """Create an agent."""
    prompt = prompt.partial(base_dir=base_dir)
    return prompt | llm


def agent_node(state: AgentState, agent, name: str):
    """Process agent node in the workflow"""
    # This is a simplified version - the full implementation would include
    # all the logic from the original agent_node function

    # Add problem statement to messages
    state["messages"] = state["messages"] + [
        HumanMessage(
            content=f"The problem statement the project is:\\n{state.get('problem_statement', '')}"
        )
    ]

    # Invoke the agent
    result = agent.invoke(state)

    # Handle different types of results
    if isinstance(result, ToolMessage):
        res = [result]
    else:
        result = AIMessage(**result.model_dump(exclude={"type", "name"}), name=name)
        res = [result]

    # Update state based on agent response
    state["update_num"] = 1
    state["invoker"] = name

    return {
        "messages": res,
        "location": state.get("location"),
        "locations": state.get("locations", []),
        "suggestion": state.get("suggestion", ""),
        "suggest_count": state.get("suggest_count", 0),
        "fix_count": state.get("fix_count", 0),
        "patch": state.get("patch"),
        "ready_to_locate": state.get("ready_to_locate", False),
        "ready_to_fix": state.get("ready_to_fix", False),
        "summary": state.get("summary", ""),
        "invoker": name,
        "next": state.get("next", ""),
        "failed_location": state.get("failed_location"),
        "update_num": state["update_num"],
        "location_content": state.get("location_content", ""),
        "problem_statement": state.get("problem_statement", ""),
    }


def parse_all_tool_calls(content: str):
    """Parse tool calls from content"""
    matches = re.findall(r"#TOOL_CALL\s+(\w+)\s+({.*?})", content, re.DOTALL)
    results = []
    for tool_name, arg_str in matches:
        try:
            args = json.loads(arg_str)
        except json.JSONDecodeError:
            args = {}
        results.append((tool_name, args))
    return results


def custom_tool_node(state: AgentState, tool_map: dict):
    """Execute custom tools based on tool calls in messages"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return state

    tool_calls = parse_all_tool_calls(last_message.content)
    if not tool_calls:
        return state

    for tool_name, args in tool_calls:
        if tool_name not in tool_map:
            continue

        call_id = uuid.uuid4().hex[:8]
        tool_fn = tool_map[tool_name]

        try:
            result = (
                tool_fn.invoke(args) if hasattr(tool_fn, "invoke") else tool_fn(**args)
            )
        except Exception as e:
            result = f"[❌ Tool execution error: {e}]"

        state["messages"].append(HumanMessage(content=f"// Tool Result:\n{result}"))

    return state