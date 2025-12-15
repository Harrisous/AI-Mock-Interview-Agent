
import os

target_file = "venv/lib/python3.11/site-packages/livekit/plugins/silero/vad.py"

if os.path.exists(target_file):
    with open(target_file, "r") as f:
        content = f.read()
    
    # Patch 1: Fix VADStream.__init__ (Already done, but safe to repeat idempotently if checked)
    if "super().__init__(vad)" in content:
        content = content.replace("super().__init__(vad)", "super().__init__()")
        print("Patched VADStream.__init__")
    else:
        print("VADStream.__init__ already patched or not found.")

    # Patch 2: Fix combine_frames -> merge_frames
    if "utils.combine_frames" in content:
        content = content.replace("utils.combine_frames", "utils.merge_frames")
        print("Patched utils.combine_frames -> utils.merge_frames")
    else:
        print("utils.combine_frames not found (already patched?)")

    with open(target_file, "w") as f:
        f.write(content)
else:
    print(f"Target file {target_file} not found.")
