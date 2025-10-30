#!/usr/bin/env python3
"""
Test script for strip_checklist_numbers function
"""
import re

def strip_checklist_numbers(text):
    """
    Strip ALL leading number prefixes from checklist items.
    """
    if not text or not isinstance(text, str):
        return text

    # Remove all leading patterns of "number. " (one or more)
    cleaned = re.sub(r'^(\d+\.\s*)+', '', text.strip())
    return cleaned.strip()

# Test cases
test_cases = [
    ("1. Check oil", "Check oil"),
    ("1. 2. Check oil", "Check oil"),
    ("1. 2. 3. Check oil", "Check oil"),
    ("Check oil", "Check oil"),
    ("1.Check oil", "Check oil"),  # No space after period
    ("1. 1. 1. 1. Check oil", "Check oil"),
    ("  1. 2. Check oil  ", "Check oil"),  # Leading/trailing spaces
    ("12. Check oil", "Check oil"),  # Multi-digit number
    ("1. 2. Check oil. Item 2. Item 3.", "Check oil. Item 2. Item 3."),  # Only strip leading
    ("", ""),
    (None, None),
]

print("Testing strip_checklist_numbers function:")
print("=" * 70)

all_passed = True
for i, (input_text, expected) in enumerate(test_cases, 1):
    result = strip_checklist_numbers(input_text)
    passed = result == expected
    all_passed = all_passed and passed

    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"\nTest {i}: {status}")
    print(f"  Input:    {repr(input_text)}")
    print(f"  Expected: {repr(expected)}")
    print(f"  Got:      {repr(result)}")

print("\n" + "=" * 70)
if all_passed:
    print("All tests PASSED! ✓")
else:
    print("Some tests FAILED! ✗")
