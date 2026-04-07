# ALERTX-Smart-Drowsiness-Detection-System
 # Driver Drowsiness Detection System v2.0

An advanced, real-time driver drowsiness detection system built with Python, OpenCV, and MediaPipe. The system continuously monitors the driver's face, tracks eye and mouth states, and alerts the user using visual, auditory, and hardware (Arduino) signals when fatigue is detected.

## Features

- **Pioneering Detection Metrics:**
  - **EAR (Eye Aspect Ratio):** Tracks eye closure to detect sleep.
  - **MAR (Mouth Aspect Ratio):** Detects yawning.
  - **PERCLOS:** Percentage of eye closure over a rolling window (industry standard).
  - **Blink Rate:** Tracks blinks per minute to identify fatigue.
  - **Head-Nod Detection:** Monitors sudden downward head movements.
- **Dynamic UI:** Real-time metrics dashboard overlaid on the camera feed, featuring live graphs of EAR and MAR.
- **Hardware Integration (Arduino):** Capable of triggering a buzzer, LED, or stopping a motor via serial communication with an Arduino when a critical drowsiness state is reached.
- **Automated Logging & Screenshots:** Auto-saves logs and captures screenshots when drowsiness events (sleep, yawn) are triggered.

## Requirements

- Python 3.8+
- A working webcam
- [Arduino](https://www.arduino.cc/) (Optional, for hardware alerts)

### Python Dependencies

Install the required packages using pip:

```bash
pip install -r requirements.txt
```

*(Key libraries: `opencv-python`, `mediapipe`, `numpy`, `pyserial`)*

## Usage

Run the main application from your terminal:

```bash
python drowsiness_detector_v2.py
```

### Command Line Arguments

You can customize the execution using various command-line arguments:

- `--port`: Arduino serial port (default: `COM5`)
- `--cam`: Camera index (default: `0`)
- `--sensitivity`: Detection sensitivity `1` (Low), `2` (Medium), `3` (High) (default: `2`)
- `--no-arduino`: Disable Arduino integration
- `--no-sound`: Mute all software alarms
- `--no-save`: Disable automatic screenshot saving

**Example:**

```bash
python drowsiness_detector_v2.py --cam 1 --sensitivity 3 --no-sound
```

## Arduino Setup (Optional)

1. Upload the sketch located in `arduino_drowsiness_alert/arduino_drowsiness_alert.ino` to your Arduino.
2. Connect your Arduino to your machine.
3. Update the COM port in your run command if it differs from the default `COM5`.
4. The system will send command signals in real-time to alert through external modules (like motors and LEDs).

## Project Structure

- `drowsiness_detector_v2.py`: The core application handling video capture, feature extraction, and alert logic.
- `requirements.txt`: Python package dependencies.
- `arduino_drowsiness_alert/`: Contains the Arduino sketch for external hardware integration.
- `alert_screenshots/`: Directory where alert screenshots are saved.
- `drowsiness_logs/`: Generates logs and session reports.

## Screenshots

*Sample alert captures:*

![Drowsy Alert](alert_screenshots/drowsy_092752_300.jpg)

![Yawn Alert](alert_screenshots/yawn_203043_041.jpg)

## Acknowledgements

- Google [MediaPipe](https://google.github.io/mediapipe/) for facial landmark detection.
- Employs classic computer vision algorithms for EAR and MAR computation.
