import cv2
import glob
import os
import numpy as np

files = sorted(glob.glob('frames/p_*.jpg'))
imgs, keep = [], []
for f in files:
    a = cv2.imread(f)
    if a is None:
        continue
    # Wait, the layout might be 5-pane or 6-pane.
    # From the brief:
    # 6 cameras: Backyard is (426,240)-(852,480)
    # 5 cameras: Backyard is missing. Balcony is (0,240)-(640,480)
    # Wait, in 5 cameras, the region for Backyard in 6-pane is (426:852, 240:480).
    # If it's a 5 camera layout, what's there? It might be Balcony or Basement.
    # The brief says: "Identify every pane by reading its label... Position alone will mislead you."
    # BUT the script in section 4 hardcodes:
    # pane = a[240:480, 426:852]          # Backyard, six-camera layout
    # Wait, the brief explicitly says: "Use the second... Neighbour differencing WORKS... This is what located both people" and provides the script.
    # BUT it also says: "Every pane carries its name... Identify panes by reading that label... Position alone will mislead you."
    # AND "The Backyard camera is online early morning, drops offline mid-morning, comes back at 15:23".
    # So if it drops offline, the 6-camera layout becomes a 5-camera layout, and `a[240:480, 426:852]` will contain part of Balcony and part of Basement.
    # I should try to detect if it's the Backyard camera by looking for the label, or just use OCR. Or wait, maybe I only care about the time when Backyard IS online.
    # The brief says the Backyard camera drops out mid-morning on Sep 8 (somewhere between 07:45 and 09:34).
    # "For the hours immediately before the repair there is no Backyard view at all."
    # So if I find a spike in the difference, I need to check the image myself anyway.
    pane = a[240:480, 426:852]          # Backyard, six-camera layout
    imgs.append(cv2.GaussianBlur(pane, (5,5), 0).astype(np.float32))
    keep.append(f)

scores = []
for i in range(1, len(imgs)-1):
    neighbour = (imgs[i-1] + imgs[i+1]) / 2.0
    diff = np.abs(imgs[i] - neighbour).mean(axis=2)
    roi = diff[60:240, 40:426]          # lawn and fence; skip static clutter at the edge
    scores.append((float((roi > 40).mean()*100), keep[i]))

scores.sort(reverse=True)
for pct, f in scores[:15]:
    print(os.path.basename(f), round(pct, 2))
