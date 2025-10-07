# TODO : 类的继承 ， 引用的函数同名问题 ，测试类判断问题 ， 编码问题

# main.py

import construct_tags
import insert
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from constants import TEST_BED, PROJECT_NAME

if __name__ == "__main__":
    dir_name = Path(TEST_BED)/PROJECT_NAME
    # dir_name = "/mnt/workspace/Test_0404"
    print("✅ Step 1: Constructing Tags...\n")
    construct_tags.run(dir_name)
    
    print("✅ Step 2: Inserting to Neo4j...\n")
    insert.run()

    print("🎉 All done!\n")
    # /var/lib/neo4j/data/databases/neo4j
