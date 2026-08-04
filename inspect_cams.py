import cv2
import os

mp4_path = "temp_vods/v2837095825.mp4" # 09:10:07 AM
cap = cv2.VideoCapture(mp4_path)
ret, frame = cap.read()
if ret:
    h, w = frame.shape[:2]
    print(f"Frame size: {w}x{h}")
    cv2.imwrite("test_layout_9_10am.jpg", frame)
    
    # Save individual camera crops
    w3 = w // 3
    h2 = h // 2
    w2 = w // 2
    
    office = frame[0:h2, 0:w3]
    front = frame[0:h2, w3:2*w3]
    kitchen = frame[0:h2, 2*w3:w]
    balcony = frame[h2:h, 0:w2]
    backyard = frame[h2:h, w2:w]
    
    cv2.imwrite("cam_office.jpg", office)
    cv2.imwrite("cam_front.jpg", front)
    cv2.imwrite("cam_kitchen.jpg", kitchen)
    cv2.imwrite("cam_balcony.jpg", balcony)
    cv2.imwrite("cam_backyard.jpg", backyard)
    print("Saved camera crops.")
cap.release()
