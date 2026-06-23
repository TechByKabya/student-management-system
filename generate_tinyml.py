import csv
import random

# 1. Generate Dataset
data = []
# Normal queue: slower dwell time (>300ms), longer inter-scan (>1500ms)
for _ in range(100):
    dwell = random.uniform(300, 800)
    inter = random.uniform(1800, 5000)
    data.append([dwell, inter, 0]) # 0 = Normal

# Proxying: fast dwell time (<250ms), very short inter-scan (<1200ms)
for _ in range(100):
    dwell = random.uniform(100, 250)
    inter = random.uniform(600, 1200)
    data.append([dwell, inter, 1]) # 1 = Proxy

with open('/Users/kabya/Desktop/Student_management_system/proxy_data.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['dwell_time_ms', 'inter_scan_time_ms', 'label'])
    writer.writerows(data)

# 2. Train Model
from sklearn.tree import DecisionTreeClassifier, export_text

X = [d[:2] for d in data]
y = [d[2] for d in data]

clf = DecisionTreeClassifier(max_depth=3, random_state=42)
clf.fit(X, y)

# 3. Export to C++ Header
cpp_code = """
#ifndef PROXY_MODEL_H
#define PROXY_MODEL_H

class ProxyModel {
public:
    static int predict(float dwell_time_ms, float inter_scan_time_ms) {
"""

tree = clf.tree_
def recurse(node, depth):
    global cpp_code
    indent = "        " + "    " * depth
    if tree.feature[node] != -2: # not a leaf
        name = "dwell_time_ms" if tree.feature[node] == 0 else "inter_scan_time_ms"
        threshold = tree.threshold[node]
        cpp_code += f"{indent}if ({name} <= {threshold:.2f}) {{\n"
        recurse(tree.children_left[node], depth + 1)
        cpp_code += f"{indent}}} else {{\n"
        recurse(tree.children_right[node], depth + 1)
        cpp_code += f"{indent}}}\n"
    else: # leaf
        value = 0 if tree.value[node][0][0] > tree.value[node][0][1] else 1
        cpp_code += f"{indent}return {value};\n"

recurse(0, 0)
cpp_code += """    }
};

#endif
"""

with open('/Users/kabya/Desktop/Student_management_system/ProxyModel.h', 'w') as f:
    f.write(cpp_code)

print("Generated proxy_data.csv and ProxyModel.h successfully!")
