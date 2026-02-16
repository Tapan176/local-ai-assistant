
import os
import sys
import fnmatch

BINARY_EXTENSIONS = {
  '.pyc', '.pyd', '.pyo', '.so', '.dll', '.exe', 
  '.png', '.jpg', '.jpeg', '.gif', '.ico', 
  '.db', '.sqlite', '.sqlite3', '.zip', '.pdf'
}

EXCLUDE_DIRS = {
  '.git', '.venv', '__pycache__', 'venv', 'node_modules', 
  '.idea', '.vscode', 'cognee_cache', 'chats', 'vault'
}

def is_text_file(filepath):
  """Check if file is text by reading a chunk."""
  try:
    with open(filepath, 'rb') as f:
      chunk = f.read(1024)
      if b'\0' in chunk:
        return False
    return True
  except Exception:
    return False

def format_file(filepath):
  """Convert CRLF to LF and 4 spaces indentation to 2 spaces."""
  try:
    if any(filepath.endswith(ext) for ext in BINARY_EXTENSIONS):
      return False

    if not is_text_file(filepath):
      return False

    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
      content = f.read()

    # 1. CRLF -> LF
    new_content = content.replace('\r\n', '\n')

    # 2. Indentation: Replace 4 spaces at start of lines with 2 spaces
    # We process line by line to handle nested indentation correctly
    lines = new_content.split('\n')
    formatted_lines = []
    for line in lines:
      stripped = line.lstrip(' ')
      if not stripped: # Empty line or only whitespace
        formatted_lines.append('')
        continue

      leading_spaces = len(line) - len(stripped)
      # Only affect indentation that is a multiple of 4? 
      # Or aggressively reduce all indentation by half?
      # User said "change space intend to 2 from 4".
      # This implies mapping 4->2, 8->4, 12->6.
      # What about 2 spaces? 2->1? Probably ignore.
      # What about 3 spaces? Ignore.

      # Simple approach: integer division by 2 for leading spaces?
      # No, that would turn 2->1.
      # Let's target multiples of 4 specifically?
      # Standard Python is multiples of 4.
      # If we just replace every 4 spaces with 2 spaces in the leading part?

      new_leading = leading_spaces
      if leading_spaces > 0:
        # Count pairs of 4 spaces
        num_blocks = leading_spaces // 4
        remainder = leading_spaces % 4
        new_leading = (num_blocks * 2) + remainder

      new_line = (' ' * new_leading) + stripped
      formatted_lines.append(new_line)

    final_content = '\n'.join(formatted_lines)

    # Write back only if changed
    # Compare with original content (handling potential original LF usage)
    # But we are forcing LF, so comparison might differ anyway.

    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
      f.write(final_content)

    return True
  except Exception as e:
    print(f"Skipped {filepath}: {e}")
    return False

def main():
  root_dir = os.getcwd()
  count = 0

  # Walk directory
  for root, dirs, files in os.walk(root_dir):
    # Filter directories in-place
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

    for file in files:
      filepath = os.path.join(root, file)
      if format_file(filepath):
        count += 1
        # print(f"Formatted: {filepath}")

  print(f"Formatted {count} files.")

if __name__ == "__main__":
  main()
