import os, sys
sys.path.append(os.path.abspath('backend'))
from c_interop import CoreWrapper
from database import get_all_students

CoreWrapper.init()
students = get_all_students()
print("Total students:", len(students))
for s in students:
    CoreWrapper.add_student(s['id'], s['name'], s['school_id'], s['phone'], 0, 0, 0, 0, 0, 0, 0, s['fingerprint_id'], s['rfid_uid'])
    
for s in students:
    uid = str(s['rfid_uid'])
    if not uid: continue
    c_st = CoreWrapper.find_by_rfid(uid)
    print(f"UID: {uid} -> Found in C:", c_st.id if c_st else "None", "(Expected:", s['id'], ")")
