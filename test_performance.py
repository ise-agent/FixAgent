#!/usr/bin/env python3
"""Performance test for find_methods_by_name optimization"""

import time
from pathlib import Path
from tools.retriever_tools import find_methods_by_name, get_retriever

def test_find_methods_performance():
    """Test the performance of find_methods_by_name"""

    print("=" * 80)
    print("Testing find_methods_by_name performance")
    print("=" * 80)

    # Ensure retriever is initialized
    retriever = get_retriever()
    print(f"\nRetriever initialized with:")
    print(f"  - {len(retriever.methods)} methods")
    print(f"  - {len(retriever.classes)} classes")
    print(f"  - {len(retriever.tags)} tags")
    print(f"  - {len(retriever.calls_index)} entities with call relationships")
    print(f"  - {len(retriever.references_index)} entities with reference relationships")

    # Test cases with different method names
    test_methods = [
        "run",
        "process",
        "execute",
        "parse",
        "init"
    ]

    print("\n" + "=" * 80)
    print("Running performance tests...")
    print("=" * 80)

    for method_name in test_methods:
        print(f"\n📊 Testing method: '{method_name}'")

        # Warm up
        _ = find_methods_by_name.invoke({"name": method_name})

        # Actual timing
        start_time = time.time()
        result = find_methods_by_name.invoke({"name": method_name})
        elapsed_time = time.time() - start_time

        # Count results (rough estimate from string length)
        result_str = str(result)
        num_matches = result_str.count("'absolute_path':")

        print(f"  ✓ Found ~{num_matches} matches")
        print(f"  ⏱️  Time: {elapsed_time:.4f} seconds")

        if elapsed_time < 0.1:
            print(f"  🚀 Excellent! (<100ms)")
        elif elapsed_time < 0.5:
            print(f"  ✅ Good (<500ms)")
        elif elapsed_time < 1.0:
            print(f"  ⚠️  Acceptable (<1s)")
        else:
            print(f"  ❌ Slow (>1s)")

    print("\n" + "=" * 80)
    print("Performance test completed!")
    print("=" * 80)

if __name__ == "__main__":
    test_find_methods_performance()
