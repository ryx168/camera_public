import cv2
import glob
import os

os.makedirs("front_car_series", exist_ok=True)
files = sorted(glob.glob("extracted_910am/*_f*.jpg"))

for f in files:
    base = os.path.basename(f)
    if "crop" in base: continue
    img = cv2.imread(f)
    h, w = img.shape[:2]
    # Front is top middle: [0:h//2, w//3: 2*w//3]
    w3 = w // 3
    h2 = h // 2
    front = img[0:h2, w3:2*w3]
    
    # Save the front crop
    out = os.path.join("front_car_series", f"front_{base}")
    cv2.imwrite(out, front)

print("Saved all front camera series.")
