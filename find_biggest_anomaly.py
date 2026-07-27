import cv2
import os
import glob
import numpy as np

folder = r"c:\camera\logs\person_frames_new"
files = glob.glob(os.path.join(folder, "*_Front.jpg"))
# also include Both since Front is contained there
files.extend(glob.glob(os.path.join(folder, "*_Both.jpg")))

print(f"Found {len(files)} candidate frames.")

# Load all images and resize them to a small standard size for fast background computation
images = []
file_paths = []
for f in files:
    img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        # Resize to 200x150 for speed
        img = cv2.resize(img, (200, 150))
        images.append(img)
        file_paths.append(f)

if not images:
    print("No images found.")
    exit()

# Compute median image
images_stack = np.stack(images, axis=0)
print("Computing median background...")
median_bg = np.median(images_stack, axis=0).astype(np.uint8)

print("Calculating scores...")
scores = []
for idx, img in enumerate(images):
    diff = cv2.absdiff(img, median_bg)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
    score = np.sum(thresh) // 255
    scores.append((score, file_paths[idx]))

scores.sort(key=lambda x: x[0], reverse=True)

print("\n--- TOP 10 ANOMALOUS FRAMES ---")
for i in range(min(15, len(scores))):
    score, path = scores[i]
    print(f"Score: {score} | File: {os.path.basename(path)}")
