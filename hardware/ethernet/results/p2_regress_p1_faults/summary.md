# P1 fault injection on the board (19 cases)

command: `python3 eth_faults.py --ip 10.8.100.230 --gap-us 20.0 --out results/p2_regress_p1_faults`

| case | expected results | got | verdict |
|---|---|---|---|
| good frame | fid 0x1 fl1 rows 8 bad 0 cks 30720; fid 0xf0000001 fl1 rows 1 bad 0 cks 10 | same | PASS |
| skipped row 3 | fid 0x2 fl2 rows 7 bad 0 cks 27719; fid 0xf0000002 fl1 rows 1 bad 0 cks 10 | same | PASS |
| bad magic on row 2 | fid 0x3 fl2 rows 7 bad 1 cks 29279; fid 0xf0000003 fl1 rows 1 bad 0 cks 10 | same | PASS |
| row 5 two pixels short | fid 0x4 fl2 rows 7 bad 1 cks 27394; fid 0xf0000004 fl1 rows 1 bad 0 cks 10 | same | PASS |
| row 5 two pixels long | fid 0x5 fl2 rows 7 bad 1 cks 28368; fid 0xf0000005 fl1 rows 1 bad 0 cks 10 | same | PASS |
| 5-byte packet inside a frame | fid 0x6 fl1 rows 8 bad 1 cks 32682; fid 0xf0000006 fl1 rows 1 bad 0 cks 10 | same | PASS |
| empty UDP payload inside a frame | fid 0x7 fl1 rows 8 bad 0 cks 31352; fid 0xf0000007 fl1 rows 1 bad 0 cks 10 | same | PASS |
| width 0 single-row frame | fid 0x8 fl1 rows 1 bad 0 cks 0; fid 0xf0000008 fl1 rows 1 bad 0 cks 10 | same | PASS |
| row index = height | fid 0x9 fl2 rows 7 bad 1 cks 29657; fid 0xf0000009 fl1 rows 1 bad 0 cks 10 | same | PASS |
| height 0 | fid 0xf000000a fl1 rows 1 bad 0 cks 10 | same | PASS |
| frame ends early (rows 0-3 of 8) | fid 0xb fl2 rows 4 bad 0 cks 16741; fid 0xf000000b fl1 rows 1 bad 0 cks 10 | same | PASS |
| bad row while no frame is open | fid 0xc fl1 rows 8 bad 0 cks 32660; fid 0xf000000c fl1 rows 1 bad 0 cks 10 | same | PASS |
| duplicate row 3 (known limitation) | fid 0xd fl1 rows 8 bad 0 cks 33852; fid 0xd fl2 rows 1 bad 0 cks 3987; fid 0xf000000d fl1 rows 1 bad 0 cks 10 | same | PASS |
| other UDP port inside a frame | fid 0xe fl1 rows 8 bad 0 cks 32454; fid 0xf000000e fl1 rows 1 bad 0 cks 10 | same | PASS |
| rows 4 and 5 swapped | fid 0xf fl1 rows 8 bad 0 cks 31627; fid 0xf000000f fl1 rows 1 bad 0 cks 10 | same | PASS |
| max width 1460, 2 rows | fid 0x10 fl1 rows 2 bad 0 cks 367331; fid 0xf0000010 fl1 rows 1 bad 0 cks 10 | same | PASS |
| frame_id wrap 0xFFFFFFFF -> 0 | fid 0xffffffff fl1 rows 8 bad 0 cks 33873; fid 0x0 fl1 rows 8 bad 0 cks 33910; fid 0xf0000011 fl1 rows 1 bad 0 cks 10 | same | PASS |
| two frames interleaved | fid 0x13 fl2 rows 1 bad 0 cks 4473; fid 0x14 fl2 rows 1 bad 0 cks 4928; fid 0x13 fl2 rows 1 bad 0 cks 4210; fid 0x14 fl2 rows 1 bad 0 cks 4735; fid 0x13 fl2 rows 1 bad 0 cks 4540; fid 0x14 fl2 rows 1 bad 0 cks 4651; fid 0x13 fl2 rows 1 bad 0 cks 3907; fid 0x14 fl2 rows 1 bad 0 cks 2994; fid 0x13 fl2 rows 1 bad 0 cks 4216; fid 0x14 fl2 rows 1 bad 0 cks 3403; fid 0x13 fl2 rows 1 bad 0 cks 4410; fid 0x14 fl2 rows 1 bad 0 cks 3411; fid 0x13 fl2 rows 1 bad 0 cks 4189; fid 0x14 fl2 rows 1 bad 0 cks 3713; fid 0x13 fl2 rows 1 bad 0 cks 4161; fid 0x14 fl2 rows 1 bad 0 cks 4452; fid 0xf0000012 fl1 rows 1 bad 0 cks 10 | same | PASS |
| good frame after all faults | fid 0x16 fl1 rows 8 bad 0 cks 33394; fid 0xf0000014 fl1 rows 1 bad 0 cks 10 | same | PASS |

**19/19 cases pass.**
