
import os
import sys

target_file = "venv/lib/python3.11/site-packages/livekit/plugins/silero/vad.py"

with open(target_file, "r") as f:
    content = f.read()

# Replace logger.exception with print to stderr
if 'logger.exception("VAD _main_task crashed")' in content:
    new_content = content.replace(
        'logger.exception("VAD _main_task crashed")',
        'import sys; sys.stderr.write(f"CRITICAL VAD FAILURE: {e}\\n"); import traceback; traceback.print_exc(file=sys.stderr); logger.exception("VAD _main_task crashed")'
    )
    with open(target_file, "w") as f:
        f.write(new_content)
    print("Updated VAD exception handler to print to stderr")
else:
    print("Could not find logger.exception call in target file. Content snippet:")
    print(content[-500:])

