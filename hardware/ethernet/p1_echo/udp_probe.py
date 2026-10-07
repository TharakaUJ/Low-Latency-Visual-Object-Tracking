import socket, sys
n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(0.3)
got = 0
for i in range(n):
    s.sendto(bytes([i & 0xFF]) * 64, ("10.8.100.230", 1234))
    try:
        s.recvfrom(2048)
        got += 1
    except OSError:
        pass
print("replies", got, "/", n)
