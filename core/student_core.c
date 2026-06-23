#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Define the maximum number of students the system can hold in memory
#define MAX_STUDENTS 100

/**
 * The Student struct definition.
 * It contains core information such as id, name, marks, attendance_count,
 * fingerprint_id, and rfid_uid. All fixed size data arrays for academic
 * simplicity.
 */
typedef struct {
  int id;               // Matches the SQLite ID for database consistency
  char name[50];        // Name up to 49 characters + null terminator
  char phone[15];       // Student phone number
  float q1, q2, q3;     // Quiz marks (max 15 each)
  float presentation;   // Presentation mark (max 7)
  float mid;            // Mid term mark (max 25)
  float final_exam;     // Final exam mark (max 40)
  float total_mark;     // Total marks (max 100)
  int attendance_count; // Number of times attended
  int fingerprint_id;   // Associated fingerprint template ID from the ESP32
                        // scanner
  char rfid_uid[20];    // Associated RFID UID string
  char school_id[20];   // Roll Number / School ID
} Student;

// Global array to hold the students in memory
Student student_db[MAX_STUDENTS];

// Global count to keep track of how many items are actually stored
int current_student_count = 0;

/**
 * Initializes the system by resetting the student count.
 * This function clears the global array memory and sets the count back to 0.
 */
void init_system() {
  current_student_count = 0;
  // Clearing the memory for safety to avoid garbage values
  memset(student_db, 0, sizeof(student_db));
  printf("[C_CORE] System initialized. Ready to accept students.\n");
}

/**
 * Adds a new student to the in-memory array.
 * It checks for boundary limits (MAX_STUDENTS).
 * Returns 1 on success, 0 if array is full.
 */
int add_student(int id, const char *name, const char *school_id,
                const char *phone, float q1, float q2, float q3,
                float presentation, float mid, float final_exam,
                int attendance_count, int fingerprint_id,
                const char *rfid_uid) {
  if (current_student_count >= MAX_STUDENTS) {
    printf("[C_CORE] Error: Student array is full!\n");
    return 0; // Failure
  }

  // Pointer to the next available student spot in the array
  Student *str = &student_db[current_student_count];

  // Assign values
  str->id = id;
  str->q1 = q1;
  str->q2 = q2;
  str->q3 = q3;
  str->presentation = presentation;
  str->mid = mid;
  str->final_exam = final_exam;

  // Calculate total mark (Average of 3 quizzes as per requirement)
  float quiz_avg = (q1 + q2 + q3) / 3.0f;
  str->total_mark = quiz_avg + presentation + mid + final_exam;

  str->attendance_count = attendance_count;
  str->fingerprint_id = fingerprint_id;

  // Copy string values
  strncpy(str->name, name, sizeof(str->name) - 1);
  str->name[sizeof(str->name) - 1] = '\0';

  strncpy(str->school_id, school_id, sizeof(str->school_id) - 1);
  str->school_id[sizeof(str->school_id) - 1] = '\0';

  strncpy(str->phone, phone, sizeof(str->phone) - 1);
  str->phone[sizeof(str->phone) - 1] = '\0';

  strncpy(str->rfid_uid, rfid_uid, sizeof(str->rfid_uid) - 1);
  str->rfid_uid[sizeof(str->rfid_uid) - 1] = '\0';

  current_student_count++;
  return 1;
}

/**
 * Searches the array for a student by their School ID (Roll Number).
 * Returns a pointer to the Student struct if found, or NULL if not found.
 */
Student *find_student_by_school_id(const char *school_id) {
  for (int i = 0; i < current_student_count; i++) {
    if (strcmp(student_db[i].school_id, school_id) == 0) {
      printf("[C_CORE] Found student by School ID: %s\n", student_db[i].name);
      return &student_db[i];
    }
  }
  printf("[C_CORE] Search failed: No student found with School ID %s\n",
         school_id);
  return NULL;
}

/**
 * Searches the array for a student by their integer fingerprint ID.
 */
Student *find_student_by_fingerprint(int fingerprint_id) {
  for (int i = 0; i < current_student_count; i++) {
    if (student_db[i].fingerprint_id == fingerprint_id) {
      return &student_db[i];
    }
  }
  return NULL;
}

/**
 * Searches the array for a student by their RFID tag UID string.
 */
Student *find_student_by_rfid(const char *rfid_uid) {
  for (int i = 0; i < current_student_count; i++) {
    if (strcmp(student_db[i].rfid_uid, rfid_uid) == 0) {
      return &student_db[i];
    }
  }
  return NULL;
}

/**
 * Increments the attendance count of a student by their SQLite ID.
 */
int update_attendance(int id) {
  for (int i = 0; i < current_student_count; i++) {
    if (student_db[i].id == id) {
      student_db[i].attendance_count++;
      return 1;
    }
  }
  return 0;
}

/**
 * Utility function to get the current count of loaded students.
 */
int get_student_count() { return current_student_count; }
