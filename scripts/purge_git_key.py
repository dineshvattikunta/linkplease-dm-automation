import subprocess
import sys
import os

key_bytes = b"dmF0dGlrdW50YWRAZ21haWwuY29t.7f4be3f30a79f9f8ffa1"
replacement = b"YOUR_API_KEY_HERE"

def replace_in_tree():
    for root, dirs, files in os.walk("."):
        if ".git" in root.split(os.sep):
            continue
        for file in files:
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "rb") as f:
                    content = f.read()
                if key_bytes in content:
                    new_content = content.replace(key_bytes, replacement)
                    with open(filepath, "wb") as f:
                        f.write(new_content)
                    print(f"Replaced key in {filepath}")
            except Exception:
                pass

if __name__ == "__main__":
    replace_in_tree()
