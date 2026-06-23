import ctypes
import os
import platform

# Determine the correct library extension based on OS
system = platform.system()
ext = ".dylib" if system == "Darwin" else ".so"
lib_path = os.path.join(os.path.dirname(__file__), "..", "core", f"libstudent{ext}")

# Load the C shared library
try:
    student_lib = ctypes.CDLL(os.path.abspath(lib_path))
except OSError as e:
    print(f"Error loading C library from {lib_path}. Please ensure you have run 'make' in the core/ directory.")
    raise e

# Define the Student struct in Python using ctypes to match C exactly
class StudentItem(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_int),
        ("name", ctypes.c_char * 50),
        ("phone", ctypes.c_char * 15),
        ("q1", ctypes.c_float),
        ("q2", ctypes.c_float),
        ("q3", ctypes.c_float),
        ("presentation", ctypes.c_float),
        ("mid", ctypes.c_float),
        ("final_exam", ctypes.c_float),
        ("total_mark", ctypes.c_float),
        ("attendance_count", ctypes.c_int),
        ("fingerprint_id", ctypes.c_int),
        ("rfid_uid", ctypes.c_char * 20),
        ("school_id", ctypes.c_char * 20)
    ]

# Setup function signatures to ensure correct argument and return types
student_lib.init_system.argtypes = []
student_lib.init_system.restype = None

# int add_student(int id, const char* name, const char* school_id, const char* phone, 
#                 float q1, float q2, float q3, float presentation, float mid, float final_exam,
#                 int attendance_count, int fingerprint_id, const char* rfid_uid)
student_lib.add_student.argtypes = [
    ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
    ctypes.c_int, ctypes.c_int, ctypes.c_char_p
]
student_lib.add_student.restype = ctypes.c_int

# Student* find_student_by_school_id(const char* school_id)
student_lib.find_student_by_school_id.argtypes = [ctypes.c_char_p]
student_lib.find_student_by_school_id.restype = ctypes.POINTER(StudentItem)

# Student* find_student_by_fingerprint(int fingerprint_id)
student_lib.find_student_by_fingerprint.argtypes = [ctypes.c_int]
student_lib.find_student_by_fingerprint.restype = ctypes.POINTER(StudentItem)

# Student* find_student_by_rfid(const char* rfid_uid)
student_lib.find_student_by_rfid.argtypes = [ctypes.c_char_p]
student_lib.find_student_by_rfid.restype = ctypes.POINTER(StudentItem)

# int update_attendance(int id)
student_lib.update_attendance.argtypes = [ctypes.c_int]
student_lib.update_attendance.restype = ctypes.c_int

# int get_student_count()
student_lib.get_student_count.argtypes = []
student_lib.get_student_count.restype = ctypes.c_int

class CoreWrapper:
    @staticmethod
    def init():
        student_lib.init_system()

    @staticmethod
    def add_student(student_id: int, name: str, school_id: str, phone: str,
                    q1: float, q2: float, q3: float, presentation: float, mid: float, final_exam: float,
                    attendance_count: int, fingerprint_id: int, rfid_uid: str) -> bool:
        name_str = (name or "").encode('utf-8')
        school_id_str = (school_id or "").encode('utf-8')
        phone_str = (phone or "").encode('utf-8')
        rfid_uid_str = (rfid_uid or "").encode('utf-8')
        result = student_lib.add_student(
            student_id,
            name_str,
            school_id_str,
            phone_str,
            q1, q2, q3, presentation, mid, final_exam,
            attendance_count,
            fingerprint_id,
            rfid_uid_str
        )
        return result == 1

    @staticmethod
    def find_by_school_id(school_id: str):
        ptr = student_lib.find_student_by_school_id(school_id.encode('utf-8'))
        if ptr:
            return ptr.contents
        return None

    @staticmethod
    def find_by_fingerprint(fingerprint_id: int):
        ptr = student_lib.find_student_by_fingerprint(fingerprint_id)
        if ptr:
            return ptr.contents
        return None

    @staticmethod
    def find_by_rfid(rfid_uid: str):
        ptr = student_lib.find_student_by_rfid(rfid_uid.encode('utf-8'))
        if ptr:
            return ptr.contents
        return None

    @staticmethod
    def update_attendance(student_id: int) -> bool:
        return student_lib.update_attendance(student_id) == 1

    @staticmethod
    def get_count() -> int:
        return student_lib.get_student_count()
