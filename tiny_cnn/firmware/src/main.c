// ============================================================================
// main.c -- NiosV firmware for the standalone tiny-cnn test system
// (quartus/tcnn_test/tcnn_test_sys.qsys), talking to tcnn_avalon_slave.sv
// over its Avalon-MM register map (see rtl/tcnn_avalon_slave.sv and
// docs/progress_log.md's Gate S1 entry) and to the host over the JTAG UART.
//
// Single-byte commands from the host:
//   'P'                          ping,          reply PONG
//   'I'                          identify,      reply TCID + u32 ID + u32 VERSION + u32 STATUS
//   'W' + u32                    scratch,       reply SCRA + u32 readback
//   'E' + u16 n + n bytes        UART echo,     reply ECHO + n bytes
//   'U' + u16 W + u16 SH + W*SH*3 B RGB   strip upload,  reply UACK + u32 checksum
//   'R' + u16 W + u16 H + u16 SH + u16 NFRAMES   run,   reply RDON + 6x u32 + u32 STATUS
//   'G' + u16 n                  read n result words,  reply GRES + n x u16
//   'X'                          soft reset,    reply XACK
//
// Every reply starts with a 4-byte ASCII magic so the host can resync past
// boot-banner text. Do NOT alt_printf anything after start-up: it would be
// interleaved with binary data on the same UART (same convention as
// fpga_cnn_pipeline/firmware/src/main.c).
// ============================================================================
#include <sys/alt_stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <io.h>
#include <fcntl.h>
#include <unistd.h>
#include <system.h>

// ---- tcnn_avalon_slave register map (rtl/tcnn_avalon_slave.sv) ------------
#define TCNN_BASE           0x00032000u
#define TCNN_REG(idx)       (TCNN_BASE + ((idx) * 4u))
#define REG_ID              0u
#define REG_VERSION         1u
#define REG_SCRATCH         2u
#define REG_CTRL            3u
#define REG_STATUS          4u
#define REG_FRAME_W         5u
#define REG_FRAME_H         6u
#define REG_STRIP_H         7u
#define REG_NFRAMES         8u
#define REG_STRIP_ADDR      9u
#define REG_STRIP_DATA      10u
#define REG_RES_ADDR        11u
#define REG_RES_DATA        12u
#define REG_CYCLES          13u
#define REG_TILES_DONE      14u
#define REG_RES_MISMATCH    15u
#define REG_MIN_GAP         16u
#define REG_MAX_GAP         17u
#define REG_FEED_STALL      18u

#define CTRL_START          (1u << 0)
#define CTRL_SOFT_RESET     (1u << 1)

#define STATUS_BUSY         (1u << 0)
#define STATUS_DONE         (1u << 1)

#define MAX_CHUNK_PIX       128u   // 384 B/chunk for UART echo/upload chunking

#define REG_READ(idx)     IORD_32DIRECT(TCNN_REG(idx), 0)
#define REG_WRITE(idx, v) IOWR_32DIRECT(TCNN_REG(idx), 0, (v))

// Generous but finite spin limit so a stuck run can't hang the firmware
// forever -- an error is still reported to the host instead of a silent hang.
#define RUN_DONE_SPIN_MAX   200000000u

// ---------------------------------------------------------------------------
// UART helpers (same pattern as fpga_cnn_pipeline/firmware/src/main.c)
// ---------------------------------------------------------------------------
static void send_all(int fd, const uint8_t *buf, size_t len)
{
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = write(fd, buf + sent, len - sent);
        if (n > 0) sent += (size_t)n;
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

static void send_u32(int fd, uint32_t v)
{
    uint8_t b[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    send_all(fd, b, 4);
}

static uint32_t recv_u32(int fd)
{
    uint8_t b[4];
    recv_all(fd, b, 4);
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static uint16_t recv_u16(int fd)
{
    uint8_t b[2];
    recv_all(fd, b, 2);
    return (uint16_t)b[0] | ((uint16_t)b[1] << 8);
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------
static void cmd_ping(int fd)
{
    send_all(fd, (const uint8_t *)"PONG", 4);
}

static void cmd_id(int fd)
{
    send_all(fd, (const uint8_t *)"TCID", 4);
    send_u32(fd, REG_READ(REG_ID));
    send_u32(fd, REG_READ(REG_VERSION));
    send_u32(fd, REG_READ(REG_STATUS));
}

static void cmd_scratch(int fd)
{
    uint32_t v = recv_u32(fd);
    REG_WRITE(REG_SCRATCH, v);
    uint32_t rb = REG_READ(REG_SCRATCH);
    send_all(fd, (const uint8_t *)"SCRA", 4);
    send_u32(fd, rb);
}

static void cmd_echo(int fd)
{
    uint16_t n = recv_u16(fd);
    uint8_t buf[MAX_CHUNK_PIX * 3];
    send_all(fd, (const uint8_t *)"ECHO", 4);
    uint16_t left = n;
    while (left > 0) {
        uint16_t chunk = (left > sizeof(buf)) ? (uint16_t)sizeof(buf) : left;
        recv_all(fd, buf, chunk);
        send_all(fd, buf, chunk);
        left -= chunk;
    }
}

// Strip upload: W x SH RGB pixels, raster order. tcnn_avalon_slave's
// STRIP_ADDR/STRIP_DATA addresses the strip at a FIXED pitch of MAX_W=640
// (see rtl/frame_player.sv), so each row must be re-seeded via STRIP_ADDR
// rather than uploaded as one tightly-packed run -- matching how
// tb/tb_slave.sv drives the same register pair in simulation.
static void cmd_upload(int fd)
{
    uint16_t w = recv_u16(fd);
    uint16_t sh = recv_u16(fd);
    uint32_t checksum = 0;
    uint8_t row_buf[640 * 3];   // one row at a time, MAX_W bound

    for (uint16_t row = 0; row < sh; row++) {
        recv_all(fd, row_buf, (size_t)w * 3);
        REG_WRITE(REG_STRIP_ADDR, (uint32_t)row * 640u);
        for (uint16_t col = 0; col < w; col++) {
            uint8_t r = row_buf[col * 3 + 0];
            uint8_t g = row_buf[col * 3 + 1];
            uint8_t b = row_buf[col * 3 + 2];
            checksum += (uint32_t)r + g + b;
            REG_WRITE(REG_STRIP_DATA, ((uint32_t)b << 16) | ((uint32_t)g << 8) | (uint32_t)r);
        }
    }

    send_all(fd, (const uint8_t *)"UACK", 4);
    send_u32(fd, checksum);
}

static void cmd_run(int fd)
{
    uint16_t w = recv_u16(fd);
    uint16_t h = recv_u16(fd);
    uint16_t sh = recv_u16(fd);
    uint16_t nframes = recv_u16(fd);

    REG_WRITE(REG_FRAME_W, w);
    REG_WRITE(REG_FRAME_H, h);
    REG_WRITE(REG_STRIP_H, sh);
    REG_WRITE(REG_NFRAMES, nframes);
    REG_WRITE(REG_CTRL, CTRL_START);

    uint32_t spins = 0;
    while (!(REG_READ(REG_STATUS) & STATUS_DONE) && spins < RUN_DONE_SPIN_MAX) spins++;

    send_all(fd, (const uint8_t *)"RDON", 4);
    send_u32(fd, REG_READ(REG_CYCLES));
    send_u32(fd, REG_READ(REG_TILES_DONE));
    send_u32(fd, REG_READ(REG_RES_MISMATCH));
    send_u32(fd, REG_READ(REG_MIN_GAP));
    send_u32(fd, REG_READ(REG_MAX_GAP));
    send_u32(fd, REG_READ(REG_FEED_STALL));
    send_u32(fd, REG_READ(REG_STATUS));
}

static void cmd_gres(int fd)
{
    uint16_t n = recv_u16(fd);
    send_all(fd, (const uint8_t *)"GRES", 4);
    for (uint16_t i = 0; i < n; i++) {
        REG_WRITE(REG_RES_ADDR, i);
        uint32_t v = REG_READ(REG_RES_DATA);
        send_u16(fd, (uint16_t)(v & 0xFFFF));
    }
}

static void cmd_abort(int fd)
{
    REG_WRITE(REG_CTRL, CTRL_SOFT_RESET);
    send_all(fd, (const uint8_t *)"XACK", 4);
}

// ---------------------------------------------------------------------------
int main(void)
{
    alt_printf("tiny-cnn test firmware ready. Cmds: P I W E U R G X\n");

    int fd = open(JTAG_UART_0_NAME, O_RDWR);
    if (fd < 0) {
        alt_printf("ERROR: could not open JTAG UART\n");
        return -1;
    }

    while (1) {
        uint8_t cmd;
        if (read(fd, &cmd, 1) <= 0) continue;

        switch (cmd) {
        case 'P': cmd_ping(fd);    break;
        case 'I': cmd_id(fd);      break;
        case 'W': cmd_scratch(fd); break;
        case 'E': cmd_echo(fd);    break;
        case 'U': cmd_upload(fd);  break;
        case 'R': cmd_run(fd);     break;
        case 'G': cmd_gres(fd);    break;
        case 'X': cmd_abort(fd);   break;
        default: break;   // ignore stray bytes
        }
    }
    return 0;
}
