# Arduino Integration

You do not paste the Python drowsiness detector into Arduino IDE.

They work together like this:

`Python detector on laptop -> USB serial -> Arduino -> buzzer / LED`

## 1. Upload the Arduino sketch

Open `arduino_drowsiness_alert/arduino_drowsiness_alert.ino` in Arduino IDE and upload it to your board.

The sketch listens for:

- `D` = alert on
- `N` = alert off

Important:

- Arduino IDE is only for the `.ino` sketch.
- The camera + OpenCV + MediaPipe code stays in Python on your laptop.
- The COM port is chosen in Python with `--port COM5`; you do not hardcode COM5 in the Arduino sketch.

## 2. Wiring

Use the relay module, buzzer, and two LEDs (with resistors):

- `D8` -> Buzzer positive pin
- `GND` -> Buzzer negative pin
- `D7` -> Relay IN pin
- `5V` -> Relay VCC pin
- `GND` -> Relay GND pin
- `D6` -> Green LED positive pin (via 220 ohm resistor)
- `GND` -> Green LED negative pin
- `D5` -> Red LED positive pin (via 220 ohm resistor)
- `GND` -> Red LED negative pin

If your hardware needs different pins, change `BUZZER_PIN`, `RELAY_PIN`, `GREEN_LED_PIN`, or `RED_LED_PIN` in the `.ino` file.

## 3. Find the Arduino COM port

In Arduino IDE, check:

- `Tools > Port`

Or in Windows Device Manager, look under `Ports (COM & LPT)`.

## 4. Close Serial Monitor

Before starting Python, close Arduino IDE Serial Monitor and Serial Plotter.  
Only one app can use the COM port at a time.

## 5. Run the Python detector

You can use either Python file below.

From this project folder:

```powershell
python drowsiness_detector_v2.py --port COM5
```

Or with your COM5 file from Downloads:

```powershell
python "C:\Users\meena\Downloads\drowsiness_detection_COM5.py" --port COM5
```

Replace `COM5` with your board's real port if needed.

If `pyserial` is missing, install dependencies first:

```powershell
pip install -r requirements.txt
```

## 6. What should happen

- When the detector starts or in normal state, Arduino turns on the GREEN LED.
- When the detector sees a drowsiness alert, Python sends `D`
- The Arduino turns off the green LED, blinks the RED LED, beeps the buzzer, and toggles the RELAY.
- When the alert clears, Python sends `N`
- The Arduino turns off the buzzer, red LED, and relay, and turns the green LED back on.

## 7. Quick test

If you want to test Arduino alone:

1. Upload the sketch
2. Open Serial Monitor
3. Set baud rate to `9600`
4. Send `D` to start alert output
5. Send `N` to stop alert output

Then close Serial Monitor before running the Python program.

## 8. What this means in practice

If your goal is to "integrate the code into Arduino IDE", the correct split is:

- Arduino IDE runs `arduino_drowsiness_alert.ino`
- Python runs the drowsiness detection script
- USB serial links the two together

An Arduino Uno cannot run the full OpenCV/MediaPipe detector by itself, so that part must stay in Python.
