/*
 * pin_probe - shield-agnostic bring-up firmware.
 *
 * Drives exactly one Arduino pin at a time so the pin map of ANY optoisolator
 * shield revision can be measured instead of guessed. Send the pin number as a
 * raw byte (2..13) to hold that pin HIGH with every other pin LOW. Send 0 to
 * release everything.
 *
 * Pins 0 and 1 are the serial port and are never touched.
 *
 * Usage:
 *   1. flash this sketch
 *   2. python -m robotron_ai.tools.discover_pad_pins --port COM3
 *   3. paste the block it prints into arduino/robotron_pad_v1 or _v2
 *   4. flash that sketch and run verify_pad_wiring
 *
 * Note: D13 also drives the Uno's onboard LED, so it blinks during reset.
 */

const int FIRST_PIN = 2;
const int LAST_PIN  = 13;

void setup() {
    Serial.begin(9600);
    for (int p = FIRST_PIN; p <= LAST_PIN; p++) {
        pinMode(p, OUTPUT);
    }
    allOff();
}

void loop() {
    if (Serial.available() > 0) {
        byte b = Serial.read();
        allOff();
        if (b >= FIRST_PIN && b <= LAST_PIN) {
            digitalWrite((int) b, HIGH);
        }
    }
}

void allOff() {
    for (int p = FIRST_PIN; p <= LAST_PIN; p++) {
        digitalWrite(p, LOW);
    }
}
