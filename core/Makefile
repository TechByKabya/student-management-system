# Compiler settings
CC = gcc
CFLAGS = -Wall -Wextra -fPIC -O2

# Determine OS for dynamic library extension and flags
UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
    # macOS
    LIB_NAME = libstudent.dylib
    LDFLAGS = -dynamiclib
else
    # Linux / others
    LIB_NAME = libstudent.so
    LDFLAGS = -shared
endif

# Default target
all: $(LIB_NAME)

# Compile student_core.c into a shared library
$(LIB_NAME): student_core.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $(LIB_NAME) student_core.c
	@echo "Successfully compiled $(LIB_NAME)"

# Clean up build files
clean:
	rm -f *.o *.so *.dylib

