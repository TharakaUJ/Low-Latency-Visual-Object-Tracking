import cv2
import numpy as np

def main():
    # 1. Open the default webcam (index 0)
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    # 2. Create a 16x16 all-white template
    # 255 represents pure white in an 8-bit grayscale image
    w, h = 16, 16
    template = np.full((h, w), 255, dtype=np.uint8)

    print("Tracking 16x16 white patches. Press 'q' to quit.")

    while True:
        # Read a frame from the webcam
        ret, frame = cap.read()
        if not ret:
            print("Error: Failed to grab frame.")
            break

        # 3. Convert the frame to grayscale for intensity comparison
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 4. Perform template matching
        # OpenCV uses TM_SQDIFF (Sum of Squared Differences) as its standard 
        # high-performance alternative to SAD. 
        result = cv2.matchTemplate(gray, template, cv2.TM_SQDIFF)

        # 5. Find the location with the minimum difference
        # For TM_SQDIFF, the lowest value represents the best match.
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        top_left = min_loc
        bottom_right = (top_left[0] + w, top_left[1] + h)

        # 6. Draw a green bounding box around the matched area
        cv2.rectangle(frame, top_left, bottom_right, (0, 255, 0), 2)

        # Display the video stream
        cv2.imshow('Webcam - White Template Match', frame)

        # Break the loop if the 'q' key is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Clean up resources
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()