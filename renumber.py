import re

with open("index.html", "r") as f:
    content = f.read()

# Step 1: Replace emojis at the end
content = content.replace("⚡ Zero-Latency Lookups", "[PERF] Zero-Latency Lookups")
content = content.replace("🤖 AI Fraud Detection", "[AI] AI Fraud Detection")
content = content.replace("📶 Universal Portability", "[API] Universal Portability")
content = content.replace("🛡️ Zero Data Loss", "[SAFE] Zero Data Loss")

# Step 2: Extract the Python ctypes block from page 5
python_block = """    <div class="rh2">Python ctypes Bridge — Calling C from Python</div>
    <div class="cb">
<span class="cm"># c_interop.py — Loading the compiled C shared library at server startup</span>
<span class="kw">import</span> ctypes, os

lib_path = os.path.join(os.path.dirname(__file__), <span class="st">'../core/libstudent.dylib'</span>)
c_lib = ctypes.CDLL(lib_path)

<span class="cm"># Define argument and return types for strict type safety</span>
c_lib.find_student_by_rfid.argtypes = [ctypes.c_char_p]
c_lib.find_student_by_rfid.restype  = ctypes.c_void_p  <span class="cm"># pointer to C struct</span>

c_lib.add_student.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_char_p, ctypes.c_float, ctypes.c_float, ctypes.c_float,
    ctypes.c_float, ctypes.c_float, ctypes.c_float,
    ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
c_lib.add_student.restype = ctypes.c_int

<span class="cm"># Usage — calling C find function from a Flask route</span>
<span class="kw">def</span> <span class="fn">find_by_rfid</span>(uid_str):
    ptr = c_lib.find_student_by_rfid(uid_str.encode(<span class="st">'utf-8'</span>))
    <span class="kw">return</span> ptr <span class="kw">if</span> ptr <span class="kw">else</span> None  <span class="cm"># C pointer or None if not found</span>
    </div>"""

if python_block in content:
    content = content.replace(python_block, "")
    
    # Create the new page 6
    new_page_6 = f"""
  <!-- PAGE 6: C-CORE ENGINE (CONTINUED) -->
  <div class="pg pg-break">
    <div class="page-num">Page 6</div>
    <div class="rh">6. Python ctypes Interoperability</div>
    <p class="rt">The bridge between the high-level Flask web server and the low-level C memory engine is built using Python's native <code>ctypes</code> library. This allows the server to load the compiled <code>.dylib</code> or <code>.so</code> shared object file directly into its memory space upon startup.</p>
    <p class="rt">By defining exact C-compatible argument types (<code>argtypes</code>) and return types (<code>restype</code>), we ensure strict type safety when marshalling data between Python objects and C structs. This zero-overhead integration allows Python to handle HTTP routing while delegating the heavy lifting entirely to C.</p>
{python_block}
    <div class="rh2">Architectural Benefit</div>
    <p class="rt">Because the shared library is loaded once at server startup, the memory is persistent across HTTP requests. The Flask routes do not need to open database connections or deserialize data to verify attendance; they simply pass a pointer to a C function, achieving sub-millisecond response times under maximum concurrent load.</p>
  </div>
"""
    # Find insertion point before Page 6 (TinyML)
    insert_point = "  <!-- PAGE 6: TINYML FRAUD DETECTION -->"
    content = content.replace(insert_point, new_page_6 + "\n" + insert_point)
    
    # Renumber pages 6 to 13 -> 7 to 14
    for i in range(13, 5, -1):
        content = content.replace(f"<!-- PAGE {i}:", f"<!-- PAGE {i+1}:")
        content = content.replace(f'<div class="page-num">Page {i}</div>', f'<div class="page-num">Page {i+1}</div>')
        content = content.replace(f'<div class="rh">{i}.', f'<div class="rh">{i+1}.')

with open("index.html", "w") as f:
    f.write(content)
