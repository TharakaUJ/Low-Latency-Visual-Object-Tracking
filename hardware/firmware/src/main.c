#include <sys/alt_stdio.h>   // alt_printf
#include <stdint.h>
#include <io.h>              // IORD_32DIRECT / IOWR_32DIRECT (cache-bypassing)
#include <fcntl.h>           // open()
#include <unistd.h>          // read()/write()/close()
#include <system.h>


// ============================================================================
// avs2 Avalon-MM Slave Base Address (NiosV -> Sdram_Control_4Port AV_* port)
// Set this to the base address Platform Designer assigned to `avs2` in your
// NiosV memory map (from DE2_115_TV_hw.tcl's `avs2` interface).
// ============================================================================
#define AVS2_BASE               0x01000000u

// ============================================================================
// Frame geometry / pixel format
// ----------------------------------------------------------------------------
// Each 32-bit SDRAM word holds TWO packed YCbCr 4:2:2 pixels, produced by the
// YUV422_to_444 / ITU_656_Decoder capture path, in ITU-R BT.656 byte order:
//
//     word[31:24] = Cr     word[23:16] = Y1     word[15:8] = Cb     word[7:0] = Y0
//
// i.e. byte order on the wire, low to high: Y0, Cb, Y1, Cr
//
// *** VERIFY THIS AGAINST YOUR YUV422_to_444.v / ITU_656_Decoder.v BEFORE
//     TRUSTING COLOR OUTPUT. If colors look swapped/wrong on the host side,
//     swap the byte order in send_frame() below to match your actual RTL. ***
//
// FRAME_WIDTH / FRAME_HEIGHT must match the *active* capture resolution your
// pipeline writes into the framebuffer (check Line_Buffer / ITU_656_Decoder
// active-window parameters). 720x480 (NTSC) is the common default for this
// board - change if you're using PAL (720x576) or a cropped window.
// ============================================================================
#define FRAME_WIDTH              720u
#define FRAME_HEIGHT             480u
#define FRAME_PIXELS             (FRAME_WIDTH * FRAME_HEIGHT)
#define FRAME_WORDS              (FRAME_PIXELS / 2u)   // 2 pixels per 32-bit word
#define FRAME_BYTES              (FRAME_PIXELS * 2u)   // 2 bytes per pixel (Y + Cb/Cr shared)

// ============================================================================
// Register access helpers (cache-bypassing, as in the original sample)
// ============================================================================
#define READ_REG(addr)          IORD_32DIRECT((addr), 0)
#define AVS2_WORD_ADDR(idx)     (AVS2_BASE + ((idx) * 4u))

// ============================================================================
// Host <-> NiosV wire protocol
// ----------------------------------------------------------------------------
//  Host -> Firmware : single command byte
//      'S'  (0x53)  -> capture + send one frame
//
//  Firmware -> Host : header, then raw pixel bytes, then a trailing checksum
//      bytes 0..3   : magic       "FRAM" (0x46 0x52 0x41 0x4D)
//      bytes 4..5   : width       little-endian uint16
//      bytes 6..7   : height      little-endian uint16
//      byte  8      : format      0x01 = packed YCbCr422, byte order Y,Cb,Y,Cr
//      bytes 9..12  : payload_len little-endian uint32 (== FRAME_BYTES)
//      bytes 13..N  : payload     raw pixel bytes, Y0 Cb Y1 Cr Y2 Cb' Y3 Cr' ...
//      bytes N+1..N+4: checksum   little-endian uint32, additive sum of all
//                                 payload bytes (mod 2^32)
//
// The host script resyncs on the "FRAM" magic, so any stray text the JTAG
// UART might emit on connect (banners etc.) is harmless - just don't print
// anything with alt_printf() while a frame send is in progress.
// ============================================================================
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

    header[0] = 'F'; header[1] = 'R'; header[2] = 'A'; header[3] = 'M';
    header[4] = (uint8_t)(FRAME_WIDTH & 0xFF);
    header[5] = (uint8_t)((FRAME_WIDTH >> 8) & 0xFF);
    header[6] = (uint8_t)(FRAME_HEIGHT & 0xFF);
    header[7] = (uint8_t)((FRAME_HEIGHT >> 8) & 0xFF);
    header[8] = 0x01; // format = packed YCbCr422
    header[9]  = (uint8_t)(FRAME_BYTES & 0xFF);
    header[10] = (uint8_t)((FRAME_BYTES >> 8) & 0xFF);
    header[11] = (uint8_t)((FRAME_BYTES >> 16) & 0xFF);
    header[12] = (uint8_t)((FRAME_BYTES >> 24) & 0xFF);

    send_all(fd, header, sizeof(header));

    for (i = 0; i < FRAME_WORDS; i++) {
        uint32_t w = READ_REG(AVS2_WORD_ADDR(i));
        uint8_t px[4];

        px[0] = (uint8_t)( w        & 0xFF); // Y0
        px[1] = (uint8_t)((w >> 8)  & 0xFF); // Cb
        px[2] = (uint8_t)((w >> 16) & 0xFF); // Y1
        px[3] = (uint8_t)((w >> 24) & 0xFF); // Cr

        checksum += (uint32_t)px[0] + px[1] + px[2] + px[3];

        send_all(fd, px, 4);
    }

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

    alt_printf("NiosV frame-grab firmware ready.\n");
    alt_printf("Send 'S' over the JTAG UART to capture+send one frame.\n");

    fd = open(JTAG_UART_0_NAME, O_RDWR);
    if (fd < 0) {
        alt_printf("ERROR: could not open /dev/jtag_uart\n");
        return -1;
    }

    while (1) {
        // Block until the host sends a command byte.
        ssize_t n = read(fd, &cmd, 1);
        if (n <= 0) {
            continue;
        }

        if (cmd == 'S') {
            send_frame(fd);
        }
        // Unknown commands are silently ignored so stray bytes don't wedge
        // the loop; extend this switch if you add more commands later.
    }

    close(fd);
    return 0;
}
