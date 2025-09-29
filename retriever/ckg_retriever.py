"""Code Knowledge Graph Retriever for Neo4j database"""
import json
from typing import List, Dict, Any, Optional

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from models.entities import Clazz, Method, Variable
from utils.decorators import singleton
from retriever.converters import convert_to_clazz, convert_to_method, convert_to_variable


@singleton
class CKGRetriever:
    """Code Knowledge Graph Retriever using Neo4j"""

    def __init__(self, uri: str, user: str, password: str):
        """Initialize the retriever with Neo4j connection parameters"""
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.focal_method_id = -1

    def close(self):
        """Close the database connection"""
        self.driver.close()

    def change_focal_method_id(self, focal_method_id: int):
        """Change the focal method ID for context-aware queries"""
        self.focal_method_id = focal_method_id

    def run_query(self, query: str, parameters: Dict[str, Any]) -> List[Any]:
        """Execute a Cypher query and return results"""
        try:
            with self.driver.session() as session:
                return [record for record in session.run(query, parameters)]
        except Neo4jError as e:
            print(f"Neo4j query failed: {e}")
            return []

    def search_method_accurately(
        self,
        absolute_path: str,
        full_qualified_name: Optional[str] = None
    ) -> List[Method]:
        """Search for methods by absolute path and optionally by full qualified name"""
        if full_qualified_name is None:
            query = """
                MATCH (n)
                WHERE (n:Method OR n:Test) AND n.absolute_path = $absolute_path
                RETURN n AS node
            """
            params = {"absolute_path": absolute_path}
        else:
            query = """
                MATCH (n)
                WHERE (n:Method OR n:Test)
                AND n.absolute_path = $absolute_path
                AND n.full_qualified_name CONTAINS $full_qualified_name
                RETURN n AS node
            """
            params = {
                "absolute_path": absolute_path,
                "full_qualified_name": full_qualified_name
            }

        results = self.run_query(query, params)
        if not results:
            print("No nodes found for the given absolute path or full qualified name.")
            return []

        return [convert_to_method(record["node"]) for record in results]

    def search_method_fuzzy(self, name: str) -> List[Method]:
        """Fuzzy search for Method and Test nodes by name"""
        query = """
            MATCH (n)
            WHERE (n:Method OR n:Test) AND n.name CONTAINS $name
            RETURN n AS node
        """
        params = {"name": name}
        results = self.run_query(query, params)

        if not results:
            print(f"No methods or tests found containing '{name}' in name.")
            return []

        return [convert_to_method(record["node"]) for record in results]

    def get_relevant_entities(self, file: str, full_qualified_name: str) -> Dict[str, List[Dict]]:
        """Find all entities related to the target entity through various relationships"""
        result = {rt: [] for rt in (
            "BELONGS_TO", "CALLS", "HAS_METHOD",
            "HAS_VARIABLE", "INHERITS", "REFERENCES"
        )}

        params = {"file": file, "fqn": full_qualified_name}

        relationship_queries = {
            "BELONGS_TO": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                MATCH (target)-[:BELONGS_TO]->(related)
                RETURN related
            """,
            "CALLS": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                MATCH (target)-[:CALLS]->(related)
                RETURN related
            """,
            "HAS_METHOD": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                OPTIONAL MATCH (target)-[:HAS_METHOD]->(related)
                OPTIONAL MATCH (related)-[:HAS_METHOD]->(target)
                WITH collect(related) AS nodes
                UNWIND nodes AS related
                RETURN DISTINCT related
            """,
            "HAS_VARIABLE": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                OPTIONAL MATCH (target)-[:HAS_VARIABLE]->(related)
                OPTIONAL MATCH (related)-[:HAS_VARIABLE]->(target)
                WITH collect(related) AS nodes
                UNWIND nodes AS related
                RETURN DISTINCT related
            """,
            "INHERITS": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                MATCH (target)-[:INHERITS]->(related)
                RETURN related
            """,
            "REFERENCES": """
                MATCH (target)
                WHERE target.absolute_path = $file
                    AND target.full_qualified_name = $fqn
                MATCH (target)-[:REFERENCES]->(related)
                RETURN related
            """
        }

        for rel_type, cypher in relationship_queries.items():
            records = self.run_query(cypher, params)
            entities = []
            for rec in records:
                node = rec["related"]
                props = dict(node.items())
                for field in ("params", "modifiers"):
                    if field in props and isinstance(props[field], str):
                        try:
                            props[field] = json.loads(props[field])
                        except json.JSONDecodeError:
                            pass
                entities.append(props)
            result[rel_type] = entities

        return result

    def read_all_classes_and_methods(self, file: str) -> tuple[List[Clazz], List[Method]]:
        """Read all classes and methods from a specific file"""
        class_query = """
            MATCH (n:Class)
            WHERE n.absolute_path = $absolute_path
            RETURN n
        """
        method_query = """
            MATCH (n:Method)
            WHERE n.absolute_path = $absolute_path
            RETURN n
        """

        params = {"absolute_path": file}
        class_results = self.run_query(class_query, params)
        method_results = self.run_query(method_query, params)

        classes = [convert_to_clazz(record[0]) for record in class_results]
        methods = [convert_to_method(record[0]) for record in method_results]

        return classes, methods

    def search_constructor_in_class(self, name: str) -> List[Method]:
        """Search for constructors in a specific class"""
        query = """
            MATCH (c:Class {name: $class_name})
            MATCH (c)-[:HAS_METHOD]->(m:Method)
            WHERE m.type = 'constructor'
            AND m.full_qualified_name STARTS WITH c.full_qualified_name + '.'
            RETURN m
        """
        params = {"class_name": name}
        records = self.run_query(query, params)
        return [convert_to_method(record["m"]) for record in records]

    def search_variable_by_name(self, file: str, variable_name: str) -> List[Variable]:
        """Search for variables by name in a specific file"""
        if '.' not in variable_name:
            query = """
                MATCH (n:Variable {name: $name, absolute_path: $file})
                RETURN DISTINCT n
            """
        else:
            query = """
                MATCH (n:Variable {absolute_path: $file})
                WHERE n.full_qualified_name CONTAINS $name
                RETURN DISTINCT n
            """

        params = {"name": variable_name, "file": file}
        with self.driver.session() as session:
            result = session.run(query, params)
            return [convert_to_variable(record["n"]) for record in result]

    def search_field_variables_of_class(self, name: str) -> List[Variable]:
        """Search for field variables of a specific class"""
        query = """
            MATCH (c:Class)-[:HAS_VARIABLE]->(v:Variable)
            WHERE c.name = $name
            RETURN v
        """
        params = {"name": name}
        results = self.run_query(query, params)
        return [convert_to_variable(record[0]) for record in results]

    def search_file_by_keyword(self, keyword: str) -> List[str]:
        """Search for files containing a specific keyword"""
        queries = [
            ("Class", "MATCH (c:Class) RETURN c.absolute_path as path, c.content as content"),
            ("Method", """
                MATCH (f:Method)
                WHERE NOT EXISTS((f)-[:BELONGS_TO]->(:Class))
                RETURN f.absolute_path as path, f.content as content
            """),
            ("Variable", """
                MATCH (v:Variable)
                WHERE NOT EXISTS((v)-[:BELONGS_TO]->(:Class))
                RETURN v.absolute_path as path, v.content as content
            """)
        ]

        all_nodes = []
        for _, query in queries:
            results = self.run_query(query, {})
            all_nodes.extend(results)

        matched_paths = set()
        for record in all_nodes:
            if record["content"] and keyword.lower() in record["content"].lower():
                matched_paths.add(record["path"])

        return list(matched_paths)

    def search_variable_by_only_name(self, variable_name: str) -> List[Variable]:
        """Search for variables by name across all files"""
        if '.' not in variable_name:
            query = """
                MATCH (n:Variable {name: $name})
                RETURN DISTINCT n
                ORDER BY n.absolute_path, n.start_line
            """
        else:
            query = """
                MATCH (n:Variable)
                WHERE n.full_qualified_name CONTAINS $name
                RETURN DISTINCT n
                ORDER BY n.absolute_path, n.start_line
            """

        params = {"name": variable_name}
        with self.driver.session() as session:
            result = session.run(query, params)
            return [convert_to_variable(rec["n"]) for rec in result]

    def search_test_cases_by_method(self, full_qualified_name: str) -> List[Method]:
        """Search for test cases related to a specific method"""
        query = """
            MATCH (m:Method { full_qualified_name: $fqn })-[:TESTED]->(tc)
            RETURN DISTINCT tc
            ORDER BY tc.absolute_path, tc.start_line
        """
        params = {"fqn": full_qualified_name}
        with self.driver.session() as session:
            result = session.run(query, params)
            return [convert_to_method(record["tc"]) for record in result]