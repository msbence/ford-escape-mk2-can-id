#include <Arduino.h>
#include <FlexCAN_T4.h>

// CAN1 (pins 22/23) = HS-CAN
FlexCAN_T4<CAN1, RX_SIZE_256, TX_SIZE_16> CAN_HS;
// CAN2 (pins 0/1) = MS-CAN
FlexCAN_T4<CAN2, RX_SIZE_256, TX_SIZE_16> CAN_MS;

void printFrame(const char* bus, const CAN_message_t &msg) {
  Serial.print(bus);
  Serial.print(" 0x");
  // zero-padding
  if (msg.id < 0x100) Serial.print("0");
  if (msg.id < 0x10)  Serial.print("0");
  Serial.print(msg.id, HEX);
  Serial.print(" [");
  Serial.print(msg.len);
  Serial.print("] ");
  
  // print each byte as hexadecimal
  for (uint8_t i = 0; i < msg.len; i++) {
    // zero padding
    if (msg.buf[i] < 0x10) Serial.print("0");
    Serial.print(msg.buf[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
  // example output: HS 0x425 [8] 00 00 23 28 02 58 28 DC 
}

void setup() {
  Serial.begin(115200); // we need more than the default 9600
  while (!Serial && millis() < 5000); // little time for the USB monitor to attach

  // init both bus, set rate, just have listen-only
  CAN_HS.begin();
  CAN_HS.setBaudRate(500000, LISTEN_ONLY);

  CAN_MS.begin();
  CAN_MS.setBaudRate(125000, LISTEN_ONLY);

  Serial.println("--[ CAN capture: READY ]--");
}

void loop() {
  CAN_message_t msg;
  
  // read both in a loop, non-blocking call
  while (CAN_HS.read(msg)) {
    printFrame("HS", msg);
  }
  
  while (CAN_MS.read(msg)) {
    printFrame("MS", msg);
  }
}
