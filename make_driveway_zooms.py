import cv2
import glob
import os
import numpy as np

os.makedirs("red_car_zooms", exist_ok=True)

# Check all images in driveway_inspect_6pm
imgs = glob.glob("driveway_inspect_6pm/*.jpg")
imgs.sort()

# Also let's inspect the entire driveway area across time
print(f"Total inspect images: {len(imgs)}")

# Let's crop Kitchen (top-right) and Front (top-mid) and check for any red or car movement
diff_reports = []
prev_k = None
prev_f = None

for img_p in imgs:
    bname = os.path.basename(img_p)
    img = cv2.imread(img_p)
    if img is None: continue
    
    kitchen = img[0:240, 853:1280]
    front = img[0:240, 426:853]
    
    # Save a side-by-side crop of driveway & front for every minute
    if "t00s" in bname or "t15s" in bname:
        combo = np.hstack([front, kitchen])
        cv2.imwrite(f"red_car_zooms/{bname}", combo)

print("Saved red_car_zooms for inspection!")
