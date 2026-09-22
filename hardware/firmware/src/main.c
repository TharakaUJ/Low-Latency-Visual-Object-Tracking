// ============================================================================
// main.c - unified NiosV firmware: frame grab + template load + boundary read
//
// Single-byte commands from the host over the JTAG UART:
//   'S'            freeze SDRAM writes, send raw frame  (format 0x02), unfreeze
//   'Y'            same but luma only, 1 byte/sample     (format 0x03), unfreeze
//   'T' + 256 B    load 16x16 template (row-major, luma), reply "TACK"+nbad
//   'R'            read template mirror back,           reply "TMPL"+256 B
//   'B'            read boundary,                       reply "BNDS"+x16+y16
//   'F' / 'U'      manual freeze / unfreeze,            reply "FRZN"+state
//   'P'            ping,                                reply "PONG"+state
//                  state: bit0 = freeze requested, bit1 = SDRAM writes really stopped
//
// Every reply starts with a 4-byte magic so the host can resync past any
// boot-banner text. Do NOT alt_printf anything after start-up: it would be
// interleaved with binary data on the same UART.
// ============================================================================
#include <sys/alt_stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <io.h>
#include <fcntl.h>
#include <unistd.h>
#include <system.h>

// ---- Avalon slave #1 (avalon_slave_top): bounds, template, control ---------
#define AVS_BASE          0x00022000u
#define AVS_REG(idx)      (AVS_BASE + ((idx) * 4u))
#define REG_BOUND_X       0u
#define REG_BOUND_Y       1u
#define REG_TMPL_BASE     2u
#define REG_CTRL          (REG_TMPL_BASE + 256u)   // word 258
#define CTRL_FREEZE       0x1u                     // write: freeze SDRAM writes
#define CTRL_FROZEN       0x2u                     // read : writes really stopped
#define WIN               16u
#define TMPL_CNT          (WIN * WIN)

// ---- Avalon slave #2: SDRAM framebuffer (one raw sample per 32-bit word) ---
#define AVS2_BASE         0x01000000u
#define AVS2_WORD_ADDR(i) (AVS2_BASE + ((i) * 4u))
#define FRAME_WIDTH       640u
#define FRAME_HEIGHT      576u
#define FRAME_WORDS       (FRAME_WIDTH * FRAME_HEIGHT)

#define FMT_RAW16         0x02
#define FMT_LUMA8         0x03

// Polls of CTRL while waiting for the RTL to confirm the freeze. If no video
// is present the RTL never sees a VS edge - but then nothing is being written
// either, so we simply carry on after the timeout.
#define FREEZE_POLL_MAX   200000u   // ~ a few hundred ms; a field is 20 ms

#define READ_REG(addr)   IORD_32DIRECT((addr), 0)

static uint32_t read_settled(uint32_t addr)
{
    (void)READ_REG(addr);   // throwaway, absorb stale value
    return READ_REG(addr);
}

// ---------------------------------------------------------------------------
// UART helpers
// ---------------------------------------------------------------------------
static void send_all(int fd, const uint8_t *buf, size_t len)
{
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = write(fd, buf + sent, len - sent);
        if (n > 0) sent += (size_t)n;   // else host not reading yet: retry
    }
}

static void recv_all(int fd, uint8_t *buf, size_t len)
{
    size_t got = 0;
    while (got < len) {
        ssize_t n = read(fd, buf + got, len - got);
        if (n > 0) got += (size_t)n;
    }
}

static void send_u16(int fd, uint16_t v)
{
    uint8_t b[2] = { (uint8_t)(v & 0xFF), (uint8_t)(v >> 8) };
    send_all(fd, b, 2);
}

// ---------------------------------------------------------------------------
// SDRAM write freeze
// ---------------------------------------------------------------------------
static int sdram_freeze(void)
{
    IOWR_32DIRECT(AVS_REG(REG_CTRL), 0, CTRL_FREEZE);
    for (uint32_t t = 0; t < FREEZE_POLL_MAX; t++)
        if (read_settled(AVS_REG(REG_CTRL)) & CTRL_FROZEN) return 1;
    return 0;   // timed out (no video?) - proceed anyway
}

static void sdram_unfreeze(void)
{
    IOWR_32DIRECT(AVS_REG(REG_CTRL), 0, 0);
}

static uint8_t freeze_state(void)
{
    return (uint8_t)(read_settled(AVS_REG(REG_CTRL)) & 0x3);
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------
static void send_frame(int fd, uint8_t fmt)
{
    const uint32_t bytes_per_word = (fmt == FMT_RAW16) ? 2u : 1u;
    const uint32_t payload_len    = FRAME_WORDS * bytes_per_word;
    uint32_t checksum = 0;

    // Header goes out FIRST so the host knows we are alive even if the freeze
    // handshake is slow or never completes (e.g. no video -> no TD_VS edges).
    send_all(fd, (const uint8_t *)"FRAM", 4);
    send_u16(fd, FRAME_WIDTH);
    send_u16(fd, FRAME_HEIGHT);
    send_all(fd, &fmt, 1);
    send_u16(fd, (uint16_t)(payload_len & 0xFFFF));
    send_u16(fd, (uint16_t)(payload_len >> 16));

    sdram_freeze();

    for (uint32_t i = 0; i < FRAME_WORDS; i++) {
        uint32_t w = read_settled(AVS2_WORD_ADDR(i));
        uint8_t lo = (uint8_t)(w & 0xFF);         // chroma byte
        uint8_t hi = (uint8_t)((w >> 8) & 0xFF);  // luma byte (YCbCr[15:8])

        if (fmt == FMT_RAW16) {
            uint8_t px[2] = { lo, hi };
            checksum += (uint32_t)lo + hi;
            send_all(fd, px, 2);
        } else {
            checksum += hi;
            send_all(fd, &hi, 1);
        }
    }

    uint8_t cs[4] = { (uint8_t)checksum, (uint8_t)(checksum >> 8),
                      (uint8_t)(checksum >> 16), (uint8_t)(checksum >> 24) };
    send_all(fd, cs, 4);

    sdram_unfreeze();
}

static void cmd_load_template(int fd)
{
    uint8_t t[TMPL_CNT];
    recv_all(fd, t, TMPL_CNT);

    for (uint32_t i = 0; i < TMPL_CNT; i++)
        IOWR_32DIRECT(AVS_REG(REG_TMPL_BASE + i), 0, t[i]);

    // avs_waitrequest stays high until the last CDC write is acked, so these
    // reads cannot complete before the final write has landed in the real array.
    uint32_t bad = 0;
    for (uint32_t i = 0; i < TMPL_CNT; i++)
        if ((read_settled(AVS_REG(REG_TMPL_BASE + i)) & 0xFF) != t[i]) bad++;

    uint8_t b = (bad > 255) ? 255 : (uint8_t)bad;
    send_all(fd, (const uint8_t *)"TACK", 4);
    send_all(fd, &b, 1);
}

static void cmd_read_template(int fd)
{
    uint8_t t[TMPL_CNT];
    for (uint32_t i = 0; i < TMPL_CNT; i++)
        t[i] = (uint8_t)(read_settled(AVS_REG(REG_TMPL_BASE + i)) & 0xFF);
    send_all(fd, (const uint8_t *)"TMPL", 4);
    send_all(fd, t, TMPL_CNT);
}

static void cmd_boundary(int fd)
{
    uint16_t x = (uint16_t)(read_settled(AVS_REG(REG_BOUND_X)) & 0x3FF);
    uint16_t y = (uint16_t)(read_settled(AVS_REG(REG_BOUND_Y)) & 0x3FF);
    send_all(fd, (const uint8_t *)"BNDS", 4);
    send_u16(fd, x);
    send_u16(fd, y);
}

// ---------------------------------------------------------------------------
int main(void)
{
    alt_printf("NiosV tracker firmware ready. Cmds: S Y T R B F U\n");

    int fd = open(JTAG_UART_0_NAME, O_RDWR);
    if (fd < 0) {
        alt_printf("ERROR: could not open JTAG UART\n");
        return -1;
    }

    sdram_unfreeze();   // make sure we never boot into a frozen display

    while (1) {
        uint8_t cmd;
        if (read(fd, &cmd, 1) <= 0) continue;

        switch (cmd) {
        case 'S': send_frame(fd, FMT_RAW16);  break;
        case 'Y': send_frame(fd, FMT_LUMA8);  break;
        case 'T': cmd_load_template(fd);      break;
        case 'R': cmd_read_template(fd);      break;
        case 'B': cmd_boundary(fd);           break;
        case 'P': {
            uint8_t s = freeze_state();
            send_all(fd, (const uint8_t *)"PONG", 4);
            send_all(fd, &s, 1);
            break;
        }
        case 'F': case 'U': {
            if (cmd == 'F') sdram_freeze(); else sdram_unfreeze();
            uint8_t s = freeze_state();
            send_all(fd, (const uint8_t *)"FRZN", 4);
            send_all(fd, &s, 1);
            break;
        }
        default: break;   // ignore stray bytes (e.g. newlines)
        }
    }
    return 0;
}
