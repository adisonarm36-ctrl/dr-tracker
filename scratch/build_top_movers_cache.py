import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
import main

print("Synchronously building top movers cache...")
main.update_movers_background()
print("Checking cache output...")
cache_file = os.path.join(os.path.dirname(__file__), "..", "backend", "top_movers_cache.json")
if os.path.exists(cache_file):
    print(f"✅ Success! Cache file generated at {cache_file} ({os.path.getsize(cache_file)} bytes)")
else:
    print("❌ Failed to generate cache file.")
