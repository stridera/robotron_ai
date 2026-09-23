/*
 * robotron_pad_v1 - serial controller firmware for the direct-wired Xbox 360 pad.
 *
 * Shield revision v1 - Strider's board, the modified one.
 *
 * Pin map MEASURED on the assembled rig 2026-09-18, all ten confirmed. D9 is
 * unused here: this board was built for D3..D12, but the D-pad-left wire was
 * moved from D9 to D13 during bring-up. D13 also drives the Uno's onboard LED,
 * so the bootloader taps D-pad left briefly on every reset, including when a
 * program opens the serial port.
 *
 * One byte in, buttons out. The byte layout is defined by SerialController in
 * control.py and MUST match the myPins[] order below:
 *
 *   bit 0  0x01  Y          fire up          bit 4  0x10  D-pad up     move up
 *   bit 1  0x02  A          fire down        bit 5  0x20  D-pad down   move down
 *   bit 2  0x04  B          fire right       bit 6  0x40  D-pad right  move right
 *   bit 3  0x08  X          fire left        bit 7  0x80  D-pad left   move left
 *
 *   0x00 releases everything.
 *   0xC0 = Start, 0x30 = Back. Safe as escapes because a direction mask never
 *   sets up+down or left+right together, so neither value is a real move byte.
 *
 * ONLY the pin numbers below differ between shield revisions. Never reorder
 * myPins[]: it is indexed by serial bit, and tests/test_control_latency.py
 * fails if it drifts from control.py.
 *
 * Verify after flashing:
 *   python -m robotron_ai.tools.verify_pad_wiring --port COM3
 */

// Measured, all ten confirmed on the rig.
const int backButton  = 3;
const int startButton = 4;

const int bButton = 5;
const int aButton = 6;
const int yButton = 7;
const int xButton = 8;

const int leftButton  = 13;
const int rightButton = 10;
const int downButton  = 11;
const int upButton    = 12;

// Index = bit position in the serial byte. Identical on every shield revision.
const int myPins[] = {
    yButton,      // bit 0  fire up
    aButton,      // bit 1  fire down
    bButton,      // bit 2  fire right
    xButton,      // bit 3  fire left
    upButton,     // bit 4  move up
    downButton,   // bit 5  move down
    rightButton,  // bit 6  move right
    leftButton    // bit 7  move left
};

const char* buttonNames[] = {"y", "a", "b", "x", "up", "down", "right", "left"};

const int button_length = 8;

const byte startMask = B11000000;
const byte backMask  = B00110000;

// Echo each command back over serial as button names. Off by default: the bot
// sends a byte per decision tick and printing would cost more than it is worth.
// Turn on only for bring-up, then reflash with it off.
const bool debug = false;

void setup() {
    Serial.begin(9600);
    for (int i = 0; i < button_length; i++) {
        pinMode(myPins[i], OUTPUT);
    }
    pinMode(backButton, OUTPUT);
    pinMode(startButton, OUTPUT);

    turnAllOff();
}

void loop() {
    if (Serial.available() > 0) {
        handleInput(Serial.read());
    }
}

void handleInput(byte b)
{
    switch (b) {
        case 0:
            turnAllOff();
            if (debug) { Serial.println("(none)"); }
            break;
        case startMask:
            turnAllOff();
            digitalWrite(startButton, HIGH);
            if (debug) { Serial.println("start"); }
            break;
        case backMask:
            turnAllOff();
            digitalWrite(backButton, HIGH);
            if (debug) { Serial.println("back"); }
            break;
        default:
            turnOn(b);
            break;
    }
}

void turnOn(byte b)
{
    // Every byte defines the whole output state, so drop start/back here too.
    // Without this a move byte after 0xC0 would leave Start held down.
    digitalWrite(startButton, LOW);
    digitalWrite(backButton, LOW);
    for (int i = 0; i < button_length; i++) {
        if ((1 << i) & b) {
            digitalWrite(myPins[i], HIGH);
            if (debug) { Serial.print(buttonNames[i]); Serial.print(" "); }
        } else {
            digitalWrite(myPins[i], LOW);
        }
    }
    if (debug) { Serial.println(); }
}

void turnAllOff()
{
    digitalWrite(startButton, LOW);
    digitalWrite(backButton, LOW);
    for (int i = 0; i < button_length; i++) {
        digitalWrite(myPins[i], LOW);
    }
}
