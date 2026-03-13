/*
 * HID Controller — Arduino Micro (ATmega32U4)
 *
 * Raw USB HID keyboard + mouse simulation.
 * Receives binary commands over USB Serial (CDC).
 *
 * ── Protocol ──────────────────────────────────────────────
 *
 *   Request:  [0xAA] [CMD] [LEN] [PAYLOAD...] [CHK]
 *   Response: [0xAA] [TYPE] [DATA] [CHK]
 *
 *   CHK = XOR of bytes between SOF and CHK (exclusive).
 *
 *   Commands (keycodes = USB HID usage IDs):
 *     0x01  PING             len=0
 *     0x10  KEY_PRESS        len=1  [keycode]   (0xE0-0xE7 = modifiers)
 *     0x11  KEY_RELEASE      len=1  [keycode]
 *     0x12  KEY_RELEASE_ALL  len=0
 *     0x13  KEY_WRITE        len=1..8 [keycodes] (tap each sequentially)
 *     0x20  MOUSE_MOVE       len=2  [dx, dy]     (int8, -128..127)
 *     0x21  MOUSE_CLICK      len=1  [buttons]    (bit0=L bit1=R bit2=M)
 *     0x22  MOUSE_PRESS      len=1  [buttons]
 *     0x23  MOUSE_RELEASE    len=1  [buttons]
 *     0x24  MOUSE_SCROLL     len=1  [amount]     (int8, -128..127)
 *
 *   Responses:
 *     0x06  ACK   data=cmd
 *     0x15  NACK  data=error (1=unknown 2=overflow 3=checksum 4=length 5=full)
 *     0x02  PONG  data=0x01
 *
 * ──────────────────────────────────────────────────────────
 */

#include <HID.h>

/* ── HID Report Descriptors ────────────────────────────── */

static const uint8_t msDesc[] PROGMEM = {
  0x05, 0x01,  // Usage Page (Generic Desktop)
  0x09, 0x02,  // Usage (Mouse)
  0xA1, 0x01,  // Collection (Application)
  0x09, 0x01,  //   Usage (Pointer)
  0xA1, 0x00,  //   Collection (Physical)
  0x85, 0x01,  //     Report ID (1)
  0x05, 0x09,  //     Usage Page (Buttons)
  0x19, 0x01,  //     Usage Minimum (1)
  0x29, 0x03,  //     Usage Maximum (3)
  0x15, 0x00,  //     Logical Minimum (0)
  0x25, 0x01,  //     Logical Maximum (1)
  0x95, 0x03,  //     Report Count (3)
  0x75, 0x01,  //     Report Size (1)
  0x81, 0x02,  //     Input (Data, Variable, Absolute)
  0x95, 0x01,  //     Report Count (1)
  0x75, 0x05,  //     Report Size (5)
  0x81, 0x03,  //     Input (Constant) - padding
  0x05, 0x01,  //     Usage Page (Generic Desktop)
  0x09, 0x30,  //     Usage (X)
  0x09, 0x31,  //     Usage (Y)
  0x09, 0x38,  //     Usage (Wheel)
  0x15, 0x81,  //     Logical Minimum (-127)
  0x25, 0x7F,  //     Logical Maximum (127)
  0x75, 0x08,  //     Report Size (8)
  0x95, 0x03,  //     Report Count (3)
  0x81, 0x06,  //     Input (Data, Variable, Relative)
  0xC0,        //   End Collection
  0xC0         // End Collection
};

static const uint8_t kbDesc[] PROGMEM = {
  0x05, 0x01,        // Usage Page (Generic Desktop)
  0x09, 0x06,        // Usage (Keyboard)
  0xA1, 0x01,        // Collection (Application)
  0x85, 0x02,        //   Report ID (2)
  0x05, 0x07,        //   Usage Page (Keyboard)
  0x19, 0xE0,        //   Usage Minimum (Left Control)
  0x29, 0xE7,        //   Usage Maximum (Right GUI)
  0x15, 0x00,        //   Logical Minimum (0)
  0x25, 0x01,        //   Logical Maximum (1)
  0x75, 0x01,        //   Report Size (1)
  0x95, 0x08,        //   Report Count (8)
  0x81, 0x02,        //   Input (Data, Variable, Absolute)
  0x95, 0x01,        //   Report Count (1)
  0x75, 0x08,        //   Report Size (8)
  0x81, 0x03,        //   Input (Constant) - reserved
  0x95, 0x06,        //   Report Count (6)
  0x75, 0x08,        //   Report Size (8)
  0x15, 0x00,        //   Logical Minimum (0)
  0x26, 0xFF, 0x00,  //   Logical Maximum (255)
  0x05, 0x07,        //   Usage Page (Keyboard)
  0x19, 0x00,        //   Usage Minimum (0)
  0x2A, 0xFF, 0x00,  //   Usage Maximum (255)
  0x81, 0x00,        //   Input (Data, Array)
  0xC0               // End Collection
};

static HIDSubDescriptor msNode(msDesc, sizeof(msDesc));
static HIDSubDescriptor kbNode(kbDesc, sizeof(kbDesc));

/* ── Protocol constants ────────────────────────────────── */

#define SOF 0xAA
#define MAX_PL 8
#define RX_TMO 200

#define CMD_PING 0x01
#define CMD_KEY_PRESS 0x10
#define CMD_KEY_RELEASE 0x11
#define CMD_KEY_REL_ALL 0x12
#define CMD_KEY_WRITE 0x13
#define CMD_MOUSE_MOVE 0x20
#define CMD_MOUSE_CLICK 0x21
#define CMD_MOUSE_PRESS 0x22
#define CMD_MOUSE_RELEASE 0x23
#define CMD_MOUSE_SCROLL 0x24

#define RSP_ACK 0x06
#define RSP_NACK 0x15
#define RSP_PONG 0x02

#define ERR_UNKNOWN 0x01
#define ERR_OVERFLOW 0x02
#define ERR_CHECKSUM 0x03
#define ERR_LENGTH 0x04
#define ERR_FULL 0x05

/* ── HID State ─────────────────────────────────────────── */

static uint8_t kbMod = 0;
static uint8_t kbKeys[6] = { 0 };
static uint8_t msBtn = 0;

static void sendKb() {
  uint8_t r[8];
  r[0] = kbMod;
  r[1] = 0;
  memcpy(&r[2], kbKeys, 6);
  HID().SendReport(2, r, 8);
}

static void sendMs(int8_t dx, int8_t dy, int8_t wh) {
  uint8_t r[4];
  r[0] = msBtn;
  r[1] = (uint8_t)dx;
  r[2] = (uint8_t)dy;
  r[3] = (uint8_t)wh;
  HID().SendReport(1, r, 4);
}

static bool kbPress(uint8_t k) {
  if (k >= 0xE0 && k <= 0xE7) {
    kbMod |= 1 << (k - 0xE0);
    return true;
  }
  for (uint8_t i = 0; i < 6; i++) {
    if (kbKeys[i] == k)
      return true;
    if (kbKeys[i] == 0) {
      kbKeys[i] = k;
      return true;
    }
  }
  return false;
}

static void kbRelease(uint8_t k) {
  if (k >= 0xE0 && k <= 0xE7) {
    kbMod &= ~(1 << (k - 0xE0));
    return;
  }
  for (uint8_t i = 0; i < 6; i++) {
    if (kbKeys[i] == k) {
      kbKeys[i] = 0;
      return;
    }
  }
}

/* ── Parser state ──────────────────────────────────────── */

enum State : uint8_t {
  S_IDLE,
  S_CMD,
  S_LEN,
  S_DATA,
  S_CHK
};

static State rxSt = S_IDLE;
static uint8_t rxCmd, rxLen, rxIdx, rxChk;
static uint8_t rxBuf[MAX_PL];
static uint32_t rxTs;

/* ── Helpers ───────────────────────────────────────────── */

static void respond(uint8_t type, uint8_t data) {
  const uint8_t pkt[4] = { SOF, type, data, (uint8_t)(type ^ data) };
  Serial.write(pkt, 4);
}

/* ── Command execution ─────────────────────────────────── */

static void execute() {
  bool ok = true;

  switch (rxCmd) {
    case CMD_PING:
      if (rxLen != 0) {
        respond(RSP_NACK, ERR_LENGTH);
        return;
      }
      respond(RSP_PONG, 0x01);
      return;

    case CMD_KEY_PRESS:
      if (rxLen == 1) {
        if (!kbPress(rxBuf[0])) {
          respond(RSP_NACK, ERR_FULL);
          return;
        }
        sendKb();
      } else
        ok = false;
      break;

    case CMD_KEY_RELEASE:
      if (rxLen == 1) {
        kbRelease(rxBuf[0]);
        sendKb();
      } else
        ok = false;
      break;

    case CMD_KEY_REL_ALL:
      kbMod = 0;
      memset(kbKeys, 0, 6);
      sendKb();
      break;

    case CMD_KEY_WRITE:
      if (rxLen >= 1) {
        for (uint8_t i = 0; i < rxLen; i++) {
          kbPress(rxBuf[i]);
          sendKb();
          kbRelease(rxBuf[i]);
          sendKb();
        }
      } else
        ok = false;
      break;

    case CMD_MOUSE_MOVE:
      if (rxLen == 2)
        sendMs((int8_t)rxBuf[0], (int8_t)rxBuf[1], 0);
      else
        ok = false;
      break;

    case CMD_MOUSE_CLICK:
      if (rxLen == 1) {
        msBtn |= rxBuf[0];
        sendMs(0, 0, 0);
        msBtn &= ~rxBuf[0];
        sendMs(0, 0, 0);
      } else
        ok = false;
      break;

    case CMD_MOUSE_PRESS:
      if (rxLen == 1) {
        msBtn |= rxBuf[0];
        sendMs(0, 0, 0);
      } else
        ok = false;
      break;

    case CMD_MOUSE_RELEASE:
      if (rxLen == 1) {
        msBtn &= ~rxBuf[0];
        sendMs(0, 0, 0);
      } else
        ok = false;
      break;

    case CMD_MOUSE_SCROLL:
      if (rxLen == 1)
        sendMs(0, 0, (int8_t)rxBuf[0]);
      else
        ok = false;
      break;

    default:
      respond(RSP_NACK, ERR_UNKNOWN);
      return;
  }

  respond(ok ? RSP_ACK : RSP_NACK, ok ? rxCmd : ERR_LENGTH);
}

/* ── Arduino entry points ──────────────────────────────── */

void setup() {
  HID().AppendDescriptor(&msNode);
  HID().AppendDescriptor(&kbNode);
  Serial.begin(115200);
}

void loop() {
  if (rxSt != S_IDLE && (millis() - rxTs) > RX_TMO) {
    rxSt = S_IDLE;
  }

  while (Serial.available()) {
    uint8_t b = Serial.read();
    rxTs = millis();

    switch (rxSt) {
      case S_IDLE:
        if (b == SOF)
          rxSt = S_CMD;
        break;

      case S_CMD:
        if (b == SOF)
          break;  // reinicia: permanece em S_CMD aguardando o CMD real

        rxCmd = b;
        rxChk = b;
        rxSt = S_LEN;
        break;

      case S_LEN:
        if (b == SOF) {
          rxSt = S_CMD;
          break;
        }
        rxLen = b;
        rxChk ^= b;
        if (rxLen > MAX_PL) {
          respond(RSP_NACK, ERR_OVERFLOW);
          rxSt = S_IDLE;
        } else if (rxLen == 0) {
          rxSt = S_CHK;
        } else {
          rxIdx = 0;
          rxSt = S_DATA;
        }
        break;

      case S_DATA:
        rxBuf[rxIdx++] = b;
        rxChk ^= b;
        if (rxIdx >= rxLen)
          rxSt = S_CHK;
        break;

      case S_CHK:
        if (b == rxChk)
          execute();
        else
          respond(RSP_NACK, ERR_CHECKSUM);
        rxSt = S_IDLE;
        break;
    }
  }
}
