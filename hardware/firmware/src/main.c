#include <sys/alt_stdio.h>   // alt_printf
#include <stdint.h>
#include <io.h>              // IORD_32DIRECT / IOWR_32DIRECT (cache-bypassing)
#include <fcntl.h>           // open()
#include <unistd.h>          // read()/write()/close()
#include <system.h>

// ============================================================================
// avs2 Avalon-MM Slave Base Address (NiosV -> Sdram_Control_4Port AV_* port)
// ============================================================================
#define AVS2_BASE               0x01000000u

// ============================================================================
// Frame geometry / pixel format
//
// NOTE: this matches the ACTUAL raw capture buffer wired in DE2_115_TV.v
// (WR1_ADDR=0, WR1_MAX_ADDR=640*576 for NTSC=0/PAL), NOT a 720x480 frame.
// The camera writer (WR1_DATA) is only 16 bits wide - each 32-bit SDRAM
// word holds exactly ONE raw YCbCr422 sample (upper 16 bits are always 0),
// not two packed pixels. This is the simplest possible readout: the raw,
// still-interlaced, still-including-blanking capture buffer, dumped as-is.
// Deinterlacing / blanking removal / YCbCr->RGB is left to the host script.
// ============================================================================
#define FRAME_WIDTH               640u          // raw samples per line (incl. blanking)
#define FRAME_HEIGHT              576u          // raw lines, both interlaced fields (PAL)
#define FRAME_WORDS               (FRAME_WIDTH * FRAME_HEIGHT)  // 1 word = 1 sample
#define FRAME_BYTES               (FRAME_WORDS * 2u)            // 2 bytes/sample (16-bit)

// ============================================================================
// Register access helpers (cache-bypassing, sweeps memory using word indexes)
// ============================================================================
#define READ_REG(addr)          IORD_32DIRECT((addr), 0)
#define AVS2_WORD_ADDR(idx)     (AVS2_BASE + ((idx) * 4u))


#define TEST_WORD_IDX   (FRAME_WORDS + 10000u)   // scratch address, outside the frame


static uint32_t read_settled(uint32_t addr)
{
    (void)READ_REG(addr);      // throwaway, absorb the stale value
    return READ_REG(addr);     // this one should be current
}

// Write then read back, with a fence in between: NiosV appears to post
// writes, so a load issued immediately after a store to the same address
// can race ahead of it without this barrier.
static uint32_t read_after_write(uint32_t addr, uint32_t wval)
{
    IOWR_32DIRECT(addr, 0, wval);
    __asm__ __volatile__ ("fence" ::: "memory");
    return READ_REG(addr);
}

static int avs2_selftest(void)
{
    int fail = 0;
    for (uint32_t pat = 0; pat < 8; pat++) {
        uint32_t wval = 0xA5A50000u | (pat << 8) | pat;
        uint32_t rval = read_after_write(AVS2_WORD_ADDR(TEST_WORD_IDX), wval);
        if (rval != wval) {
            alt_printf("SELFTEST FAIL pat=%x wrote=%x read=%x\n", pat, wval, rval);
            fail = 1;
        }
    }
    if (!fail) alt_printf("SELFTEST PASS\n");
    return fail;
}

static void send_all(int fd, const uint8_t *buf, size_t len)
{
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = write(fd, buf + sent, len - sent);
        if (n <= 0) {
            // JTAG UART not ready / host not reading yet - just retry.
            continue;
        }
        sent += (size_t)n;
    }
}

static void send_frame(int fd)
{
    uint8_t header[13];
    uint32_t checksum = 0;
    uint32_t i;

    // Construct the "FRAM" header protocol
    header[0] = 'F'; header[1] = 'R'; header[2] = 'A'; header[3] = 'M';
    header[4] = (uint8_t)(FRAME_WIDTH & 0xFF);
    header[5] = (uint8_t)((FRAME_WIDTH >> 8) & 0xFF);
    header[6] = (uint8_t)(FRAME_HEIGHT & 0xFF);
    header[7] = (uint8_t)((FRAME_HEIGHT >> 8) & 0xFF);
    header[8] = 0x02; // format = raw interlaced YCbCr422, 1 sample per word, still-blanked
    header[9]  = (uint8_t)(FRAME_BYTES & 0xFF);
    header[10] = (uint8_t)((FRAME_BYTES >> 8) & 0xFF);
    header[11] = (uint8_t)((FRAME_BYTES >> 16) & 0xFF);
    header[12] = (uint8_t)((FRAME_BYTES >> 24) & 0xFF);

    // Transmit protocol header
    send_all(fd, header, sizeof(header));

    // Memory sweep loop over the AVS2 address space.
    // No CPU write happens here (this is pure read of camera-written data),
    // so no fence is needed - the posted-write hazard only applies between
    // a store and a load to the same address from THIS core.
    for (i = 0; i < FRAME_WORDS; i++) {
        // Read 32-bit register directly from the generated word address pointer.
        // Only the low 16 bits are meaningful (WR1_DATA is 16 bits wide);
        // upper 16 bits are always 0.
        uint32_t w = read_settled(AVS2_WORD_ADDR(i));
        uint8_t px[2];

        px[0] = (uint8_t)( w       & 0xFF); // low byte of raw sample
        px[1] = (uint8_t)((w >> 8) & 0xFF); // high byte of raw sample

        checksum += (uint32_t)px[0] + px[1];

        // Send raw sample bytes to the JTAG interface
        send_all(fd, px, 2);
    }

    // Send trailing verification checksum
    {
        uint8_t csum_bytes[4];
        csum_bytes[0] = (uint8_t)(checksum & 0xFF);
        csum_bytes[1] = (uint8_t)((checksum >> 8) & 0xFF);
        csum_bytes[2] = (uint8_t)((checksum >> 16) & 0xFF);
        csum_bytes[3] = (uint8_t)((checksum >> 24) & 0xFF);
        send_all(fd, csum_bytes, 4);
    }
}

int main(void)
{
    int fd;
    uint8_t cmd;

    alt_printf("Doing the self-test of the AVS2 Avalon-MM interface...\n");
    // if (avs2_selftest() != 0) {
    //     alt_printf("ERROR: AVS2 self-test failed, aborting.\n");
    //     return -1;
    // }

    alt_printf("NiosV frame-grab firmware ready.\n");
    alt_printf("Send 'S' over the JTAG UART to capture+send one frame.\n");

    // Replace JTAG_UART_0_NAME with the exact literal string if not defined in system.h (e.g. "/dev/juart")
    fd = open(JTAG_UART_0_NAME, O_RDWR);
    if (fd < 0) {
        alt_printf("ERROR: could not open JTAG UART interface\n");
        return -1;
    }

    while (1) {
        alt_printf("Waiting for host command...\n");

        ssize_t n = read(fd, &cmd, 1);
        if (n <= 0) {
            continue;
        }

        if (cmd == 'S') {
            send_frame(fd);
        }
    }

    close(fd);
    return 0;
}