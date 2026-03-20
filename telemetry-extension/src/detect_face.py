import sys

try:
    import cv2
    import os
except ImportError:
    print("0")
    sys.exit(0)

def main():
    try:
        # Use default camera
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("0")
            return
            
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            print("0")
            return
            
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if not os.path.exists(cascade_path):
            print("0")
            return
            
        face_cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
        
        if len(faces) > 0:
            print("1")
        else:
            print("0")
    except Exception:
        print("0")

if __name__ == "__main__":
    main()
