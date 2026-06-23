import re

with open("index.html", "r") as f:
    lines = f.readlines()

pages = [2, 3, 6, 8, 10, 11, 12]

for i, line in enumerate(lines):
    if "<!-- PAGE " in line:
        m = re.search(r'<!-- PAGE (\d+):', line)
        if m:
            page_num = int(m.group(1))
            if page_num in pages:
                if i + 1 < len(lines) and '<div class="pg pg-break">' in lines[i+1]:
                    lines[i+1] = lines[i+1].replace('<div class="pg pg-break">', '<div class="pg pg-break space-out">')

content = "".join(lines)
css_rule = "\n.space-out { justify-content: space-between !important; }\n</style>"
content = content.replace("</style>", css_rule)

with open("index.html", "w") as f:
    f.write(content)
