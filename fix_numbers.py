import re

with open("index.html", "r") as f:
    content = f.read()

# Fix the duplicate page 7 issue
# The first one is ctypes, should be 6
ctypes_page = """  <!-- PAGE 7: C-CORE ENGINE (CONTINUED) -->
  <div class="pg pg-break">
    <div class="page-num">Page 7</div>
    <div class="rh">7. Python ctypes Interoperability</div>"""
fixed_ctypes = """  <!-- PAGE 6: PYTHON CTYPES BRIDGE -->
  <div class="pg pg-break">
    <div class="page-num">Page 6</div>
    <div class="rh">6. Python ctypes Interoperability</div>"""
content = content.replace(ctypes_page, fixed_ctypes)

with open("index.html", "w") as f:
    f.write(content)
