import cv2
from ultralytics import YOLO

# Load trained model
model = YOLO("best.pt")

# Open video
cap = cv2.VideoCapture("road_video.mp4")

frame_width = int(cap.get(3))
frame_height = int(cap.get(4))

# Save output video
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter("output_video.mp4", fourcc, 20.0, (frame_width, frame_height))

# Store counted pothole IDs

counted_ids = set()
pothole_count = 0

while cap.isOpened():

    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLO with tracking
    results = model.track(frame, persist=True, verbose=False)

    for result in results:

        boxes = result.boxes

        if boxes.id is None:
            continue

        for box, track_id in zip(boxes.xyxy, boxes.id):

            x1, y1, x2, y2 = map(int, box)
            track_id = int(track_id)

           

           # Bounding box dimensions
            width = x2 - x1
            height = y2 - y1
            box_area = width * height

            # Frame area
            frame_area = frame.shape[0] * frame.shape[1]

            # Raw size ratio
            size_ratio = box_area / frame_area

            # Distance correction (based on vertical position)
            center_y = (y1 + y2) / 2
            distance_factor = center_y / frame.shape[0]

            # Adjusted size
            adjusted_size = size_ratio * (1 + distance_factor)

            # Severity classification
            if adjusted_size < 0.015:
                severity = "Minor"
                color = (0,255,0)

            elif adjusted_size < 0.04:
                severity = "Moderate"
                color = (0,255,255)

            else:
                severity = "Severe"
                color = (0,0,255)
                        
            # Count unique potholes
            if track_id not in counted_ids:
                counted_ids.add(track_id)
                pothole_count += 1

            # Draw bounding box
            cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)

            label = f"Pothole {track_id} | {severity}"

            cv2.putText(frame,label,(x1,y1-10),
                        cv2.FONT_HERSHEY_SIMPLEX,0.6,color,2)

    # Display total potholes
    cv2.putText(frame,f"Total Potholes: {pothole_count}",
                (20,40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255,0,0),
                3)

    cv2.imshow("Pothole Detection",frame)

    out.write(frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
out.release()
cv2.destroyAllWindows()