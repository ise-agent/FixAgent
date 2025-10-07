"""Code Knowledge Graph Retriever for Neo4j database"""
import json
from typing import List, Dict, Any, Optional

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from models.entities import Clazz, Method, Variable
from utils.decorators import singleton
from retriever.converters import _convert_to_clazz, _convert_to_method, _convert_to_variable


@singleton
class CKGRetriever:

    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.focal_method_id = -1
    def close(self):
        self.driver.close()
    def change_focal_method_id(self, focal_method_id):
        self.focal_method_id = focal_method_id
    def run_query(self, query: str, parameters: dict) -> List[Any]:
        """
        通用查询方法，运行 Cypher 查询并返回结果。

        :param query: Cypher 查询字符串
        :param parameters: 查询参数字典
        :return: 查询结果的记录列表
        """
        try:
            with self.driver.session() as session:
                return [record for record in session.run(query, parameters)]
        except Neo4jError as e:
            print(f"Neo4j query failed: {e}")
            return []

    def search_method_accurately(self, absolute_path: str, full_qualified_name: str = None) -> List[Any]:
        if full_qualified_name is None:
            check_query = """
                MATCH (n)
                WHERE (n:Method OR n:Test) AND n.absolute_path = $absolute_path
                RETURN n AS node
            """
            check_params = {"absolute_path": absolute_path}
        else:
            check_query = """
                MATCH (n)
                WHERE (n:Method OR n:Test)
                AND n.absolute_path = $absolute_path
                AND n.full_qualified_name CONTAINS $full_qualified_name
                RETURN n AS node
            """
            check_params = {
                "absolute_path": absolute_path,
                "full_qualified_name": full_qualified_name
            }

        check_result = self.run_query(check_query, check_params)

        if not check_result:
            print("No nodes found for the given absolute path or full qualified name.")
            return [] 

        nodes = [_convert_to_method(record["node"]) for record in check_result]
        return nodes

    def search_method_fuzzy(self, name: str) -> List[Method]:
        """
        模糊查找 Method 和 Test 节点
        """
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

        nodes = [_convert_to_method(record["node"]) for record in results]
        return nodes
    


    def get_relevant_entities(self, file: str, full_qualified_name: str) -> dict:
        """
        查找与目标实体相关的所有关系节点

        Args:
            file: 目标实体的绝对路径（对应节点的 absolute_path 属性）
            full_qualified_name: 目标实体的全限定名（如 'MyClass.my_method'）

        Returns:
            Dict[str, List[dict]]: 包含六类关系的字典，键为关系类型，值为相关节点属性字典列表
        """
        result = {rt: [] for rt in (
            "BELONGS_TO", "CALLS", "HAS_METHOD",
            "HAS_VARIABLE", "INHERITS", "REFERENCES"
        )}

        params = {"file": file, "fqn": full_qualified_name}

        # 各关系的 Cypher 查询
        relationship_cyphers = {
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

        # 执行查询并解析结果
        for rel_type, cypher in relationship_cyphers.items():
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

    def read_all_classes_and_methods(self, file):
            class_query = '''MATCH (n:Class)
                WHERE n.absolute_path = $absolute_path
                RETURN n
                '''
            parameters = {"absolute_path": file}
            class_result = self.run_query(class_query, parameters)
            method_query = '''MATCH (n:Method)
                WHERE n.absolute_path = $absolute_path
                RETURN n
                '''
            method_result = self.run_query(method_query, parameters)
            return [_convert_to_clazz(cnode[0]) for cnode in class_result], [_convert_to_method(mnode[0]) for mnode in method_result]
    
    def search_constructor_in_clazz(self, name: str) -> List[Method]:
        """
        根据类名查找对应的构造函数
        
        Args:
            name: 目标类名（精确匹配）
            
        Returns:
            List[Method]: 匹配到的构造函数对象列表（通常每个类只有一个构造函数）
        """
        query = """
           
            MATCH (c:Class {name: $class_name})
            MATCH (c)-[:HAS_METHOD]->(m:Method)
            WHERE m.type = 'constructor'  
            AND m.full_qualified_name STARTS WITH c.full_qualified_name + '.' 
            RETURN m
        """
        params = {"class_name": name}
        records = self.run_query(query, params)
        return [_convert_to_method(record["m"]) for record in records]
    

    def search_variable_query(self, file: str,variable_name: str) -> List[Any]:
        """
        查询与所给方法距离最近的 Variable 节点。

        :param file: path of the file
        :param variable_name: Variable 节点的 name 属性
        :return: 包含 Variable 节点和距离的列表，按距离升序排列
        """
        if '.' not in variable_name:
            query = """
                    MATCH (n:Variable {name: $name, absolute_path: $file})
                    RETURN DISTINCT n
                    """
        else:
            query = """
                    MATCH (n:Variable {absolute_path: $file})
                    WHERE n.full_qualified_name contains $name
                    RETURN DISTINCT n
                    """
        parameters = {"name": variable_name, "file": file}

        with self.driver.session() as session:
            result = session.run(query, parameters)
            nodes = [_convert_to_variable(record["n"]) for record in result]
            return nodes
        
    def search_field_variables_of_class(self, name: str) -> List[Variable]:
        variable_query = """MATCH (c:Class)-[:HAS_VARIABLE]->(v:Variable)
            WHERE c.name = $name
            RETURN v
            """
        parameters = {"name": name}
        result = self.run_query(variable_query, parameters)
        return [_convert_to_variable(vnode[0]) for vnode in result]
    def search_file_by_keyword(self, keyword):
    
        class_query = '''
        MATCH (c:Class)
        RETURN c.absolute_path as path, c.content as content
        '''
        class_results = self.run_query(class_query,{})

        standalone_func_query = '''
        MATCH (f:Method)
        WHERE NOT EXISTS((f)-[:BELONGS_TO]->(:Class))
        RETURN f.absolute_path as path, f.content as content
        '''
        func_results = self.run_query(standalone_func_query,{})

    
        standalone_var_query = '''
        MATCH (v:Variable)
        WHERE NOT EXISTS((v)-[:BELONGS_TO]->(:Class))
        RETURN v.absolute_path as path, v.content as content
        '''
        var_results = self.run_query(standalone_var_query,{})

    
        all_nodes = []
        all_nodes.extend(class_results)
        all_nodes.extend(func_results)
        all_nodes.extend(var_results)

    
        matched_paths = set()
        for record in all_nodes:
            if record["content"] and keyword.lower() in record["content"].lower():
                matched_paths.add(record["path"])

        return list(matched_paths)

    def search_variable_by_only_name_query(self, variable_name: str) -> List[Variable]:
            """
            Query all Variable nodes whose simple name equals `variable_name`, or if
            `variable_name` contains a dot (.), whose fully‐qualified name contains it.

            :param variable_name: either the exact 'name' property or a fragment of 'full_qualified_name'
            :return: list of Variable domain objects
            """
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
                return [_convert_to_variable(rec["n"]) for rec in result]

    def search_test_cases_by_method_query(self, full_qualified_name: str) -> List[Any]:
        """
        Query all test‐case nodes connected by a TESTED edge from the Method node
        whose full_qualified_name exactly matches.

        :param full_qualified_name: the fully‐qualified name of the method under test
        :return: list of test‐case domain objects, ordered by file and start line
        """
        query = """
            MATCH (m:Method { full_qualified_name: $fqn })-[:TESTED]->(tc)
            RETURN DISTINCT tc
            ORDER BY tc.absolute_path, tc.start_line
        """
        params = {"fqn": full_qualified_name}
        with self.driver.session() as session:
            result = session.run(query, params)
            # assumes a helper to convert graph node -> TestCase object
            return [_convert_to_method(record["tc"]) for record in result]