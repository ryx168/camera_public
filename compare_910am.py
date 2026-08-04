import cv2
import glob
import os

# Compare frame 01 of v2837100234 (09:09:00) vs v2837102050 (09:11:50)
f_start = cv2.imread("real_910am_frames/09_09_00_v2837100234_f01.jpg")
f_end = cv2.imread("real_910am_frames/09_11_50_v2837102050_f01.jpg")

h, w = f_start.shape[:2]
w3 = w // 3
h2 = h // 2

# Front camera is top middle
front_start = f_start[0:h2, w3:2*w3]
front_end = f_end[0:h2, w3:2*w3]

cv2.imwrite("detected_car_motion/car_at_09_09_00.jpg", front_start)
cv2.imwrite("detected_car_motion/car_at_09_11_50.jpg", front_end)

# Also check kitchen camera (top right)
kitchen_start = f_start[0:h2, 2*w3:w]
kitchen_end = f_end[0:h2, 2*w3:w]

cv2.imwrite("detected_car_motion/kitchen_at_09_09_00.jpg", kitchen_start)
cv2.imwrite("detected_car_motion/kitchen_at_09_11_50.jpg", kitchen_end)

print("Saved start and end images for comparison.")
