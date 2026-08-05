import glob

files = glob.glob("kitchen_deep_inspect/2026-08-04_061*.jpg")
files.sort()
for f in files:
    print(f)
