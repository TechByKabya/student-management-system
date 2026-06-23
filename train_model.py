import m2cgen as m2c
from sklearn.ensemble import RandomForestClassifier
import numpy as np

# Synthetic Data for RFID Scans (dwell_time_ms, inter_scan_time_ms)
# Class 0: Normal (inter_scan_time > 3000ms OR dwell_time > 1500ms)
# Class 1: Proxy Burst (inter_scan_time <= 3000ms AND dwell_time <= 1500ms)

X = []
y = []

# Generate Normal Data
for _ in range(500):
    dwell = np.random.uniform(50, 5000)
    inter = np.random.uniform(3100, 20000) # Normal slow scans
    X.append([dwell, inter])
    y.append(0)

# Generate Proxy Data
for _ in range(500):
    dwell = np.random.uniform(50, 1500)
    inter = np.random.uniform(50, 3000) # Fast consecutive scans
    X.append([dwell, inter])
    y.append(1)

# Generate Edge Cases
X.extend([[1400, 2900], [1600, 2900], [1400, 3100], [1600, 3100]])
y.extend([1, 0, 0, 0])

X = np.array(X)
y = np.array(y)

clf = RandomForestClassifier(n_estimators=3, max_depth=3, random_state=42)
clf.fit(X, y)

code = m2c.export_to_c(clf)

header = f"""
#ifndef PROXY_MODEL_H
#define PROXY_MODEL_H

// This file was auto-generated using m2cgen and scikit-learn
// Model: RandomForestClassifier (n_estimators=3, max_depth=3)
// Features: [dwell_time_ms, inter_scan_time_ms]

class ProxyModel {{
public:
    static int predict(float dwell_time_ms, float inter_scan_time_ms) {{
        double input[2] = {{(double)dwell_time_ms, (double)inter_scan_time_ms}};
        return score(input) > 0.5 ? 1 : 0;
    }}
private:
    static double score(double * input);
}};

{code.replace('void score', 'double ProxyModel::score')}

#endif
"""

with open("ProxyModel.h", "w") as f:
    f.write(header)

print("ProxyModel.h generated successfully!")
