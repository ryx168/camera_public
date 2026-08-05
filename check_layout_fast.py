import cv2
import os

img = cv2.imread("car_610pm_results/ref_v2837518857.jpg")
if img is not None:
    h, w = img.shape[:2]
    print(f"Frame resolution: {w}x{h}")
    # Let's save standard crops:
    # 5-camera standard layout:
    # Top row: 3 cameras [w//3 width each, h//2 height]
    # Bot row: 2 cameras [w//2 width each, h//2 height]
    w3 = w // 3
    w2 = w // 2
    h2 = h // 2
    
    cv2.imwrite("car_610pm_results/sample_top_left.jpg", img[0:h2, 0:w3])
    cv2.imwrite("car_610pm_results/sample_top_mid.jpg", img[0:h2, w3:2*w3])
    cv2.imwrite("car_610pm_results/sample_top_right.jpg", img[0:h2, 2*w3:w])
    cv2.imwrite("car_610pm_results/sample_bot_left.jpg", img[h2:h, 0:w2])
    cv2.imwrite("car_610pm_results/sample_bot_right.jpg", img[h2:h, w2:w])
    print("Saved standard 5-cam crops successfully!")
