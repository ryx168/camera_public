import cv2
import os

img = cv2.imread("extracted_910am/09_10_07_v2837095825_f01.jpg")
h, w = img.shape[:2]
w3 = w // 3
h2 = h // 2
w2 = w // 2

# Top row (3 cameras)
office = img[0:h2, 0:w3]
front = img[0:h2, w3:2*w3]
kitchen = img[0:h2, 2*w3:w]

# Bottom row (2 cameras)
balcony = img[h2:h, 0:w2]
backyard = img[h2:h, w2:w]

cv2.imwrite("extracted_910am/crop_01_office.jpg", office)
cv2.imwrite("extracted_910am/crop_02_front.jpg", front)
cv2.imwrite("extracted_910am/crop_03_kitchen.jpg", kitchen)
cv2.imwrite("extracted_910am/crop_04_balcony.jpg", balcony)
cv2.imwrite("extracted_910am/crop_05_backyard.jpg", backyard)
print("Saved 5 camera crops.")
