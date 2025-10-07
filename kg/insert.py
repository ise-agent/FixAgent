from py2neo import Graph
import json
import sys
from collections import defaultdict
from bisect import bisect_right
from typing import Tuple, List ,Dict, Optional
from tqdm import tqdm
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"
'''
{"fname": "", "rel_fname": "", "line": [12, 12], "name": "Apps", "kind": "def", "category": "class", "info": ""}
{"fname": "", "rel_fname": "", "line": [107, 107], "name": "join", "kind": "ref", "category": "function", "info": ""}

'''
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

# patch: optimize Neo4jImporter batching for nodes & rels with UNWIND


class Neo4jImporter:
    def __init__(self):
        self.graph = Graph(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self._ensure_constraints()        
        self._await_indexes()
        self.nodes_to_create: dict[str, dict[str, dict]] = defaultdict(dict)
        self.rels_to_create: list[tuple[str, str, str, str, str]] = []

    def clear_database(self):
        self.graph.run("MATCH (n) DETACH DELETE n")

    def get_or_create_node(self, label: str, primary_key: str, properties: dict):
        bucket = self.nodes_to_create[label]
        if primary_key in bucket:
            bucket[primary_key].update(properties or {})
        else:
            bucket[primary_key] = dict(properties or {})
        return primary_key

    def create_relationship(self, start_label, end_label, rel_type, start_key, end_key):
        self.rels_to_create.append((start_label, end_label, rel_type, start_key, end_key))

    def _ensure_constraints(self):
        stmts = [
            """
            CREATE CONSTRAINT class_fqn IF NOT EXISTS
            FOR (c:Class) REQUIRE c.full_qualified_name IS UNIQUE
            """,
            """
            CREATE CONSTRAINT method_fqn IF NOT EXISTS
            FOR (m:Method) REQUIRE m.full_qualified_name IS UNIQUE
            """,
            """
            CREATE CONSTRAINT variable_fqn IF NOT EXISTS
            FOR (v:Variable) REQUIRE v.full_qualified_name IS UNIQUE
            """,
        ]
        for s in stmts:
            self.graph.run(s)

    def _await_indexes(self, timeout_sec: int = 300):
        try:
            self.graph.run(f"CALL db.awaitIndexes({timeout_sec})")
        except Exception:
            pass

    def _bulk_merge_nodes_for_label(self, label: str, items: dict[str, dict], batch_size: int):
        if not items:
            return
        rows = [{"fqn": fqn, "props": props} for fqn, props in items.items()]
        for i in range(0, len(rows), batch_size):
            sub = rows[i:i + batch_size]
            self.graph.run(f"""
            UNWIND $rows AS row
            MERGE (n:`{label}` {{full_qualified_name: row.fqn}})
            SET n += row.props
            """, rows=sub)

    def _bulk_merge_relationships(self, batch_size: int):
        if not self.rels_to_create:
            return

        groups: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
        for start_label, end_label, rel_type, start_key, end_key in self.rels_to_create:
            groups[(start_label, end_label, rel_type)].append((start_key, end_key))

        for (s_label, e_label, rel_type), pairs in groups.items():
            rel_rows = [{"s": s, "t": t} for s, t in pairs]
            for i in range(0, len(rel_rows), batch_size):
                sub = rel_rows[i:i + batch_size]
                self.graph.run(f"""
                UNWIND $rels AS r
                MATCH (a:`{s_label}` {{full_qualified_name: r.s}})
                MATCH (b:`{e_label}` {{full_qualified_name: r.t}})
                MERGE (a)-[rel:`{rel_type}`]->(b)
                """, rels=sub)

    def commit(self, batch_size=20000):
        for label, items in self.nodes_to_create.items():
            self._bulk_merge_nodes_for_label(label, items, batch_size)
        self.nodes_to_create.clear()

        self._bulk_merge_relationships(batch_size)
        self.rels_to_create.clear()

    def process_structure(self, structure, current_path=None):
        if current_path is None:
            current_path = []
        for key, value in structure.items():
            if key.endswith(".py") and isinstance(value, dict):
                for class_data in value.get("classes", []):
                    self.process_class(class_data)
                for func in value.get("functions", []):
                    self.process_method(func, is_class_method=False)
                for var in value.get("variables", []):
                    var['class_name'] = None
                    self.process_variable(var)
            elif isinstance(value, dict):
                self.process_structure(value, current_path + [key])

    def process_class(self, class_data):
        class_props = {
            "name": class_data["name"],
            "absolute_path": class_data["absolute_path"],
            "start_line": class_data["start_line"],
            "end_line": class_data["end_line"],
            "content": "\n".join(class_data["content"]),
            "class_type": class_data["class_type"],
            "parent_class": class_data["parent_class"]
        }
        self.get_or_create_node("Class", class_data["full_qualified_name"], class_props)

        if class_data["parent_class"]:
            self.create_relationship("Class", "Class", "INHERITS",
                                     class_data["full_qualified_name"],
                                     class_data["parent_class"])

        for method in class_data["methods"]:
            self.process_method(method, is_class_method=True)

        for const in class_data["constants"]:
            self.process_variable(const)

    def process_method(self, method_data, is_class_method):
        label = "Method"
        method_props = {
            "name": method_data["name"],
            "absolute_path": method_data["absolute_path"],
            "start_line": method_data["start_line"],
            "end_line": method_data["end_line"],
            "content": "\n".join(method_data["content"]),
            "params": json.dumps(method_data["params"]),
            "modifiers": json.dumps(method_data["modifiers"]),
            "signature": method_data["signature"],
            "type": method_data["type"]
        }
        self.get_or_create_node(label, method_data["full_qualified_name"], method_props)

        if is_class_method and method_data["class_name"]:
            self.create_relationship("Class", label, "HAS_METHOD",
                                     method_data["class_name"],
                                     method_data["full_qualified_name"])
            self.create_relationship(label, "Class", "BELONGS_TO",
                                     method_data["full_qualified_name"],
                                     method_data["class_name"])

    def process_variable(self, var_data):
        var_props = {
            "name": var_data["name"],
            "absolute_path": var_data["absolute_path"],
            "start_line": var_data["start_line"],
            "end_line": var_data["end_line"],
            "content": "\n".join(var_data["content"]),
            "modifiers": json.dumps(var_data.get("modifiers", [])),
            "data_type": var_data["data_type"]
        }
        self.get_or_create_node("Variable", var_data["full_qualified_name"], var_props)

        if var_data["class_name"]:
            self.create_relationship(
                "Class", "Variable", "HAS_VARIABLE",
                var_data["class_name"],
                var_data["full_qualified_name"]
            )
            self.create_relationship(
                "Variable", "Class", "BELONGS_TO",
                var_data["full_qualified_name"],
                var_data["class_name"]
            )


class Neo4jRefImporter:
    def __init__(self, graph: Graph):
        self.graph = graph
        self.file_intervals: Dict[str, List[Tuple[int, int, str, str, str]]] = defaultdict(list)
        self.name_targets: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self.pending_rels: List[Tuple[str, str, str, str, str]] = []
        self.ambiguous: List[dict] = []
        self.missing_src: List[dict] = []
        self.missing_dst: List[dict] = []

    
    def preload_indexes(self):
        for label in ("Method", "Class"):
            cursor = self.graph.run(f"""
            MATCH (n:`{label}`)
            RETURN n.absolute_path AS path,
                   n.start_line    AS s,
                   n.end_line      AS e,
                   n.full_qualified_name AS fqn,
                   n.name          AS name
            """)
            for row in cursor:
                path, s, e, fqn, name = row["path"], row["s"], row["e"], row["fqn"], row["name"]
                if not (path and isinstance(s, int) and isinstance(e, int)):
                    continue
                self.file_intervals[path].append((s, e, fqn, label, name))
                self.name_targets[(label, name)].append(fqn)

        for path in self.file_intervals:
            self.file_intervals[path].sort(key=lambda t: t[0])

    def _find_container(self, path: str, line: int) -> Optional[Tuple[str, str]]:
        """
        return (fqn, label) or None
        """
        intervals = self.file_intervals.get(path)
        if not intervals:
            return None

        starts = [s for (s, _, _, _, _) in intervals]
        idx = bisect_right(starts, line) - 1
        candidates = []
        for j in range(max(0, idx - 5), min(len(intervals), idx + 6)):
            s, e, fqn, label, name = intervals[j]
            if s <= line <= e:
                candidates.append((s, e, fqn, label, name))
        if not candidates:
            return None
        methods = [c for c in candidates if c[3] == "Method"]
        chosen = methods or candidates
        chosen.sort(key=lambda c: (c[3] != "Method", c[1] - c[0]))
        _, _, fqn, label, _ = chosen[0]
        return fqn, label

    def load_refs_from_tags(self, tags_path: str):
        """
        读取行式 JSON（tags.json），只处理 kind == 'ref' 的记录。
        """
        with open(tags_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in tqdm(lines, desc="解析 tags 引用", unit="line"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            kind = rec.get("kind")
            if kind != "ref":
                continue

            fname = rec.get("fname") or rec.get("rel_fname")
            lval = rec.get("line")
            if isinstance(lval, list) and lval:
                line_no = int(lval[0])
            elif isinstance(lval, int):
                line_no = lval
            else:
                continue

            name = rec.get("name")
            category = (rec.get("category") or "").lower() 

            src = self._find_container(fname, line_no)
            if not src:
                self.missing_src.append({"file": fname, "line": line_no, "name": name, "category": category})
                continue
            src_fqn, src_label = src

            if category == "function":
                t_label = "Method"
                rel_type = "CALLS"
            elif category == "class":
                t_label = "Class"
                rel_type = "REFERENCES"
            else:
                continue

            candidates = self.name_targets.get((t_label, name), [])
            if not candidates:
                self.missing_dst.append({"file": fname, "line": line_no, "name": name, "t_label": t_label})
                continue
            if len(candidates) > 1:
                self.ambiguous.append({
                    "file": fname, "line": line_no, "name": name,
                    "t_label": t_label, "candidates": candidates[:10]  
                })
                continue

            dst_fqn = candidates[0]
            self.pending_rels.append((src_fqn, dst_fqn, src_label, t_label, rel_type))

        self.pending_rels = list(dict.fromkeys(self.pending_rels))



    def await_indexes(self, timeout_sec: int = 300):
        try:
            self.graph.run(f"CALL db.awaitIndexes({timeout_sec})")
        except Exception:
            pass
    def commit(self, batch_size: int = 1000):
        if not self.pending_rels:
            return

        groups = defaultdict(list)  # (s_label, t_label, rtype) -> [(s_fqn, t_fqn), ...]
        for s_fqn, t_fqn, s_label, t_label, rtype in self.pending_rels:
            groups[(s_label, t_label, rtype)].append((s_fqn, t_fqn))

        for (s_label, t_label, rtype), pairs in groups.items():
            with tqdm(total=len(pairs), desc=f"写入关系 {rtype}", unit="rel") as pbar:
                for i in range(0, len(pairs), batch_size):
                    sub = pairs[i:i + batch_size]
                    rows = [{"s": s, "t": t} for s, t in sub]

                    self.graph.run(f"""
                    UNWIND $rels AS r
                    MATCH (a:`{s_label}` {{full_qualified_name: r.s}})
                    MATCH (b:`{t_label}` {{full_qualified_name: r.t}})
                    MERGE (a)-[:`{rtype}`]->(b)
                    """, rels=rows)

                    pbar.update(len(sub))

        self.pending_rels.clear()

    
def run():
    kg_path = Path(__file__).resolve().parent / "kg.json"
    tags_path = Path(__file__).resolve().parent / "tags.json"

    print("Loading config")
    with open(kg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        root_key = next(iter(data.keys())) if isinstance(data, dict) else None
        structure = data[root_key] if root_key else data
    print("✅")


    print("Begin to process structure")
    importer = Neo4jImporter()
    importer.clear_database()
    importer.process_structure(structure)
    importer.commit()
    print("✅")


    print("Begin to process references")
    g = Graph(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    ref = Neo4jRefImporter(g)
    ref.await_indexes() 
    ref.preload_indexes()                
    ref.load_refs_from_tags(tags_path) 
    ref.commit()  
    print("数据导入完成")
    print("✅") 

