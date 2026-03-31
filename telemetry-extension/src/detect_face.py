import os
import platform
import sys
import time

try:
    import cv2
except ImportError:
    print("0")
    print("[detect_face] OpenCV import failed", file=sys.stderr)
    sys.exit(0)


def open_camera():
    is_windows = platform.system().lower().startswith("win")
    backends = []
    if is_windows and hasattr(cv2, "CAP_DSHOW"):
        backends.append(("CAP_DSHOW", cv2.CAP_DSHOW))
    backends.append(("DEFAULT", None))

    for camera_index in (0, 1):
        for backend_name, backend in backends:
            cap = cv2.VideoCapture(camera_index, backend) if backend is not None else cv2.VideoCapture(camera_index)
            if cap.isOpened():
                print(
                    f"[detect_face] Camera opened on index {camera_index} with backend {backend_name}",
                    file=sys.stderr,
                )
                return cap
            cap.release()

    return None


def read_frame(cap):
    # Give the webcam a moment to warm up before grabbing a frame.
    for _ in range(5):
        ret, frame = cap.read()
        if ret and frame is not None:
            return frame
        time.sleep(0.2)
    return None


def main():
    cap = None
    try:
        cap = open_camera()
        if cap is None:
            print("0")
            print("[detect_face] Could not open camera on indexes 0 or 1", file=sys.stderr)
            return

        frame = read_frame(cap)
        if frame is None:
            print("0")
            print("[detect_face] Camera opened, but no frame could be read", file=sys.stderr)
            return

        cascade_path = os.path.join(os.path.dirname(cv2.__file__), 'data', 'haarcascade_frontalface_default.xml')
        if not os.path.exists(cascade_path):
            # fallback to common system paths on Linux
            fallback_paths = [
                '/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml',
                '/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml',
            ]
            for p in fallback_paths:
                if os.path.exists(p):
                    cascade_path = p
                    break

        if not os.path.exists(cascade_path):
            print("0")
            print(f"[detect_face] Cascade file missing: {cascade_path}", file=sys.stderr)
            return

        face_cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))

        if len(faces) > 0:
            print("1")
            print(f"[detect_face] Face detected. Count: {len(faces)}", file=sys.stderr)
        else:
            print("0")
            print("[detect_face] No face detected in captured frame", file=sys.stderr)
    except Exception as exc:
        print("0")
        print(f"[detect_face] Unexpected error: {exc}", file=sys.stderr)
    finally:
        if cap is not None:
            cap.release()

if __name__ == "__main__":
    main()
