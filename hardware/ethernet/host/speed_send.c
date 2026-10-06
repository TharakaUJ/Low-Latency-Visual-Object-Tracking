/* speed_send: paced P3 frame sender for the speed test (speed3.py). Sends frames at a fixed rate
 * (or back to back), one UDP packet per row (P3 row protocol, p3_track/rtl/row_stats.v), one
 * sendmmsg per frame, and logs the 44-byte result packets in a receiver thread with kernel
 * receive timestamps.
 *
 *   speed_send <ip> <port> <frames.bin> <nframes> <h> <w> <fps> <fid0> <sends.bin> <results.bin>
 *   fps 0 = line rate (no pacing). frames.bin = nframes * h * w bytes.
 *   sends.bin:   per frame  u32 fid, u32 pad, i64 t_first_ns, i64 t_last_ns       (CLOCK_REALTIME)
 *   results.bin: per result 44-byte packet, 4 pad bytes, i64 t_recv_ns             (SO_TIMESTAMPNS)
 * Results are collected until 1 s after the last frame.
 * Build: gcc -O2 -pthread -o speed_send speed_send.c
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAXROWS 1024
#define RESLEN 44

static int64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}

static int sock;
static FILE *fres;
static volatile int stop_rx = 0;
static long nres = 0;

static void *rx_thread(void *arg) {
    (void)arg;
    unsigned char buf[2048], ctl[256];
    struct pollfd pf = {.fd = sock, .events = POLLIN};
    while (!stop_rx) {
        if (poll(&pf, 1, 20) <= 0) continue;
        for (;;) {
            struct iovec iov = {.iov_base = buf, .iov_len = sizeof buf};
            struct msghdr m = {.msg_iov = &iov, .msg_iovlen = 1, .msg_control = ctl, .msg_controllen = sizeof ctl};
            ssize_t n = recvmsg(sock, &m, MSG_DONTWAIT);
            if (n < 0) break;
            int64_t t = now_ns();
            for (struct cmsghdr *c = CMSG_FIRSTHDR(&m); c; c = CMSG_NXTHDR(&m, c))
                if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SO_TIMESTAMPNS) {
                    struct timespec ts;
                    memcpy(&ts, CMSG_DATA(c), sizeof ts);
                    t = (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
                }
            if (n != RESLEN) continue;
            unsigned char rec[RESLEN + 4 + 8] = {0};
            memcpy(rec, buf, RESLEN);
            memcpy(rec + RESLEN + 4, &t, 8);
            fwrite(rec, sizeof rec, 1, fres);
            nres++;
        }
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 11) {
        fprintf(stderr, "usage: speed_send ip port frames.bin nframes h w fps fid0 sends.bin results.bin\n");
        return 2;
    }
    const char *ip = argv[1];
    int port = atoi(argv[2]);
    long nf = atol(argv[4]);
    int h = atoi(argv[5]), w = atoi(argv[6]);
    double fps = atof(argv[7]);
    uint32_t fid0 = (uint32_t)strtoul(argv[8], NULL, 0);
    if (h > MAXROWS || w > 1460) { fprintf(stderr, "frame too large\n"); return 2; }

    size_t fsz = (size_t)h * w;
    unsigned char *frames = malloc(fsz * nf);
    FILE *ff = fopen(argv[3], "rb");
    if (!ff || fread(frames, fsz, nf, ff) != (size_t)nf) { fprintf(stderr, "cannot read frames\n"); return 1; }
    fclose(ff);
    FILE *fs = fopen(argv[9], "wb");
    fres = fopen(argv[10], "wb");
    if (!fs || !fres) { perror("open out"); return 1; }

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    int big = 16 << 20, one = 1;
    setsockopt(sock, SOL_SOCKET, SO_SNDBUF, &big, sizeof big);
    setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &big, sizeof big);
    setsockopt(sock, SOL_SOCKET, SO_TIMESTAMPNS, &one, sizeof one);
    struct sockaddr_in dst = {.sin_family = AF_INET, .sin_port = htons(port)};
    inet_pton(AF_INET, ip, &dst.sin_addr);

    pthread_t th;
    pthread_create(&th, NULL, rx_thread, NULL);

    static unsigned char pk[MAXROWS][12 + 1460];
    static struct iovec iov[MAXROWS];
    static struct mmsghdr mm[MAXROWS];
    int64_t t0 = now_ns() + 20000000LL;
    long eagain = 0;
    for (long k = 0; k < nf; k++) {
        uint32_t fid = fid0 + (uint32_t)k;
        for (int r = 0; r < h; r++) {
            uint16_t mg = 0x5AA5, rr = r, ww = w, hh = h;
            memcpy(pk[r] + 0, &mg, 2); memcpy(pk[r] + 2, &fid, 4); memcpy(pk[r] + 6, &rr, 2);
            memcpy(pk[r] + 8, &ww, 2); memcpy(pk[r] + 10, &hh, 2);
            memcpy(pk[r] + 12, frames + (size_t)k * fsz + (size_t)r * w, w);
            iov[r].iov_base = pk[r]; iov[r].iov_len = 12 + w;
            memset(&mm[r], 0, sizeof mm[r]);
            mm[r].msg_hdr.msg_name = &dst; mm[r].msg_hdr.msg_namelen = sizeof dst;
            mm[r].msg_hdr.msg_iov = &iov[r]; mm[r].msg_hdr.msg_iovlen = 1;
        }
        if (fps > 0) {
            int64_t due = t0 + (int64_t)(k * 1e9 / fps);
            while (now_ns() < due) ;
        }
        int64_t a = now_ns();
        int sent = 0;
        while (sent < h) {
            int n = sendmmsg(sock, mm + sent, h - sent, 0);
            if (n < 0) {
                if (errno == EAGAIN || errno == ENOBUFS) { eagain++; continue; }
                perror("sendmmsg"); return 1;
            }
            sent += n;
        }
        int64_t b = now_ns();
        unsigned char rec[24] = {0};
        memcpy(rec, &fid, 4); memcpy(rec + 8, &a, 8); memcpy(rec + 16, &b, 8);
        fwrite(rec, 24, 1, fs);
    }
    int64_t end = now_ns() + 1000000000LL;
    while (now_ns() < end) usleep(10000);
    stop_rx = 1;
    pthread_join(th, NULL);
    fclose(fs); fclose(fres);
    fprintf(stderr, "speed_send: %ld frames sent, %ld results, %ld send retries\n", nf, nres, eagain);
    return 0;
}
