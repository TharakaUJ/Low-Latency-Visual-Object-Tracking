/* burst_send: send ROI frames to the DE2-115 at line rate (one sendmmsg per frame, one UDP packet
 * per row, P2 row protocol) and log result packets with kernel receive timestamps.
 *
 *   burst_send <ip> <port> <frames.bin> <nframes> <roi> <mode> <fid0> <out.bin>
 *   mode 0: one frame in flight (send a frame, wait up to 50 ms for its result, then the next)
 *   mode 1: burst (all frames back to back, results collected on the fly and for 1 s after)
 * frames.bin = nframes * roi * roi bytes. out.bin = 56-byte records:
 *   'S' u32 fid, i64 t_send_first_ns, i64 t_send_last_ns      (CLOCK_REALTIME)
 *   'R' 40-byte result packet, i64 t_recv_ns                   (kernel SO_TIMESTAMPNS)
 * Build: gcc -O2 -o burst_send burst_send.c
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAXROWS 512
#define REC 56

static int64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}

static FILE *out;

static void put_send(uint32_t fid, int64_t t0, int64_t t1) {
    unsigned char r[REC] = {0};
    r[0] = 'S';
    memcpy(r + 8, &fid, 4);
    memcpy(r + 16, &t0, 8);
    memcpy(r + 24, &t1, 8);
    fwrite(r, 1, REC, out);
}

/* receive one result packet if available within timeout_ms; returns its frame_id or -1 */
static int64_t recv_one(int s, int timeout_ms) {
    struct pollfd p = {s, POLLIN, 0};
    if (poll(&p, 1, timeout_ms) <= 0) return -1;
    unsigned char buf[2048], cbuf[256];
    struct iovec iov = {buf, sizeof buf};
    struct msghdr m = {0};
    m.msg_iov = &iov;
    m.msg_iovlen = 1;
    m.msg_control = cbuf;
    m.msg_controllen = sizeof cbuf;
    ssize_t n = recvmsg(s, &m, MSG_DONTWAIT);
    if (n != 40) return -1;
    int64_t t = now_ns();
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&m); c; c = CMSG_NXTHDR(&m, c))
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SO_TIMESTAMPNS) {
            struct timespec ts;
            memcpy(&ts, CMSG_DATA(c), sizeof ts);
            t = (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
        }
    unsigned char r[REC] = {0};
    r[0] = 'R';
    memcpy(r + 8, buf, 40);
    memcpy(r + 48, &t, 8);
    fwrite(r, 1, REC, out);
    uint16_t magic;
    uint32_t fid;
    memcpy(&magic, buf, 2);
    memcpy(&fid, buf + 4, 4);
    return magic == 0x3CC3 ? (int64_t)fid : -2;
}

int main(int argc, char **argv) {
    if (argc != 9) {
        fprintf(stderr, "usage: %s ip port frames.bin nframes roi mode fid0 out.bin\n", argv[0]);
        return 2;
    }
    const char *ip = argv[1];
    int port = atoi(argv[2]), nfr = atoi(argv[4]), roi = atoi(argv[5]), mode = atoi(argv[6]);
    uint32_t fid0 = (uint32_t)strtoul(argv[7], 0, 0);
    if (roi <= 0 || roi > MAXROWS || roi > 1460) return 2;
    FILE *f = fopen(argv[3], "rb");
    if (!f) { perror("frames"); return 1; }
    size_t fsz = (size_t)nfr * roi * roi;
    unsigned char *pix = malloc(fsz);
    if (fread(pix, 1, fsz, f) != fsz) { fprintf(stderr, "short frames file\n"); return 1; }
    fclose(f);
    out = fopen(argv[8], "wb");
    if (!out) { perror("out"); return 1; }

    int s = socket(AF_INET, SOCK_DGRAM, 0);
    int one = 1, big = 8 << 20;
    setsockopt(s, SOL_SOCKET, SO_SNDBUF, &big, sizeof big);
    setsockopt(s, SOL_SOCKET, SO_RCVBUF, &big, sizeof big);
    setsockopt(s, SOL_SOCKET, SO_TIMESTAMPNS, &one, sizeof one);
    struct sockaddr_in dst = {0};
    dst.sin_family = AF_INET;
    dst.sin_port = htons(port);
    inet_pton(AF_INET, ip, &dst.sin_addr);
    if (connect(s, (struct sockaddr *)&dst, sizeof dst)) { perror("connect"); return 1; }

    static unsigned char pk[MAXROWS][12 + 1460];
    struct iovec iov[MAXROWS];
    struct mmsghdr msg[MAXROWS];
    int got = 0, timeouts = 0;
    for (int k = 0; k < nfr; k++) {
        uint32_t fid = fid0 + k;
        for (int r = 0; r < roi; r++) {
            uint16_t magic = 0x5AA5, row = r, w = roi, h = roi;
            memcpy(pk[r] + 0, &magic, 2);
            memcpy(pk[r] + 2, &fid, 4);
            memcpy(pk[r] + 6, &row, 2);
            memcpy(pk[r] + 8, &w, 2);
            memcpy(pk[r] + 10, &h, 2);
            memcpy(pk[r] + 12, pix + ((size_t)k * roi + r) * roi, roi);
            iov[r].iov_base = pk[r];
            iov[r].iov_len = 12 + roi;
            memset(&msg[r], 0, sizeof msg[r]);
            msg[r].msg_hdr.msg_iov = &iov[r];
            msg[r].msg_hdr.msg_iovlen = 1;
        }
        int64_t t0 = now_ns();
        int sent = 0;
        while (sent < roi) {
            int n = sendmmsg(s, msg + sent, roi - sent, 0);
            if (n < 0) {
                if (errno == EINTR || errno == ENOBUFS || errno == EAGAIN) continue;
                perror("sendmmsg");
                return 1;
            }
            sent += n;
        }
        int64_t t1 = now_ns();
        put_send(fid, t0, t1);
        if (mode == 0) {
            int64_t end = now_ns() + 50000000LL;
            int done = 0;
            while (!done && now_ns() < end) {
                int64_t r = recv_one(s, 5);
                if (r == (int64_t)fid) done = 1;
                if (r >= 0) got++;
            }
            if (!done) timeouts++;
        } else {
            while (recv_one(s, 0) != -1) got++;
        }
    }
    int64_t end = now_ns() + 1000000000LL;
    while (now_ns() < end) {
        if (recv_one(s, 20) >= 0) got++;
    }
    fclose(out);
    fprintf(stderr, "frames sent %d, results %d, mode-0 timeouts %d\n", nfr, got, timeouts);
    return 0;
}
