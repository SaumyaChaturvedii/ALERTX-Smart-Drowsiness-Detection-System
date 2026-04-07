/*
  Sleep Drowsiness System - Arduino Receiver
  ------------------------------------------------------
  Hardware Setup:
  - Relay Module (Motor): Pin 7
  - Red LED: Pin 5
  - Green LED (Optional safe indicator): Pin 6
  - Buzzer (Optional): Pin 8
  
  Commands from Python:
  - 'D3' / 'D2' = Sleep / Critical -> STOP Motor & GLOW Red Light
  - 'D1' = Warning 
  - 'N'  = Normal / Awake -> RUN Motor & GLOW Green Light
*/

const int RED_LED_PIN = 5;     // Connect red LED here
const int GREEN_LED_PIN = 6;   // Connect green LED here
const int RELAY_PIN = 7;       // Connect relay module here (controls motor)
const int BUZZER_PIN = 8;      // Optional buzzer

// Variable to track the current state
String currentState = "N";

void setup() {
  // Initialize Serial Communication with Python (Baud rate MUST match Python)
  Serial.begin(9600);
  Serial.setTimeout(50);
  
  // Set pins as outputs
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // Start in Normal/Awake State
  setNormalState();
}

void loop() {
  // Check if Python script is sending data
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    
    // Update state based on command from Python
    if (cmd == 'N') {
      setNormalState();
    } 
    else if (cmd == 'D') {
      // 'D' means drowsiness alert (eyes closed, nodding, yawning, etc.)
      setSleepState();
    }
  }
}

// ---- STATE FUNCTIONS ----

void setNormalState() {
  // Person is awake - Motor runs, Green light
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(RED_LED_PIN, LOW);
  
  // Note: Most relay modules are Active LOW. 
  // LOW = Relay ON (Motor runs). HIGH = Relay OFF. 
  // Change these if your relay behaves backward!
  digitalWrite(RELAY_PIN, LOW); 
  
  noTone(BUZZER_PIN); // Buzzer off
}

void setWarningState() {
  // Optional warning state
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(RELAY_PIN, LOW); // Motor keeps running
  tone(BUZZER_PIN, 1000); // Small beep
}

void setSleepState() {
  // PERSON IS SLEEPING! 
  // 1. Stop the motor (HIGH turns off most relay modules)
  digitalWrite(RELAY_PIN, HIGH);
  
  // 2. Glow red light
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, HIGH);
  
  // Optional: Loud buzzer sound
  tone(BUZZER_PIN, 2000); 
}
