# P2 offline ZSAD over OTB-100 (ROI 80, target 16 px, fixed template)

command: `python3 zsad_offline.py --roi 80 --target-px 16 --out ../results/p2_offline`

100 targets: mean P@20 34.7, median 23.9; mean AUC (fixed box size) 27.1. Information only.

| target | frames | scaled frame | P@20 | AUC | mean err (orig px) | lost % | reject % | attributes |
|---|---|---|---|---|---|---|---|---|
| Dancer2 | 150 | 67x54 | 100.0 | 75.3 | 7.1 | 0.0 | 0.0 | Deformation |
| BlurCar3 | 357 | 143x107 | 99.4 | 79.6 | 4.2 | 0.3 | 0.0 | Motion Blur Fast Motion |
| BlurFace | 493 | 99x74 | 99.4 | 77.8 | 8.7 | 0.0 | 0.0 | Motion Blur Fast Motion In-Plane Rotation |
| Jumping | 313 | 168x138 | 99.4 | 70.7 | 4.3 | 0.3 | 2.6 | Motion Blur Fast Motion |
| BlurOwl | 631 | 137x103 | 98.9 | 79.8 | 5.6 | 1.0 | 1.1 | Scale Variation Motion Blur Fast Motion In-Plane Rotation |
| BlurCar1 | 742 | 97x73 | 98.4 | 77.8 | 6.9 | 1.3 | 0.0 | Motion Blur Fast Motion |
| Gym | 767 | 123x68 | 96.9 | 48.5 | 10.2 | 0.3 | 8.6 | Out-of-Plane Rotation Scale Variation Deformation In-Plane Rotation |
| Walking | 412 | 282x212 | 95.9 | 53.2 | 7.1 | 0.0 | 0.0 | Scale Variation Occlusion Deformation Low Resolution |
| FaceOcc1 | 892 | 41x34 | 90.8 | 74.1 | 21.8 | 7.2 | 0.0 | Occlusion |
| Boy | 602 | 267x200 | 87.7 | 68.5 | 9.9 | 10.0 | 19.1 | Out-of-Plane Rotation Scale Variation Motion Blur Fast Motion In-Plane Rotation |
| Jogging-1 | 307 | 112x92 | 86.9 | 64.9 | 17.4 | 12.7 | 0.0 | Out-of-Plane Rotation Occlusion Deformation |
| Dancer | 225 | 74x57 | 84.4 | 59.4 | 13.0 | 0.0 | 52.7 | Out-of-Plane Rotation Scale Variation Deformation In-Plane Rotation |
| Skater | 160 | 70x53 | 83.0 | 55.8 | 13.2 | 0.0 | 63.5 | Out-of-Plane Rotation Scale Variation Deformation In-Plane Rotation |
| FaceOcc2 | 812 | 57x43 | 79.2 | 68.7 | 13.1 | 0.5 | 64.4 | Illumination Variation Out-of-Plane Rotation Occlusion In-Plane Rotation |
| Jogging-2 | 307 | 87x71 | 76.8 | 60.1 | 24.1 | 14.1 | 0.0 | Out-of-Plane Rotation Occlusion Deformation |
| BlurCar2 | 585 | 93x70 | 76.7 | 60.0 | 49.8 | 23.1 | 0.0 | Scale Variation Motion Blur Fast Motion |
| Subway | 175 | 181x148 | 75.3 | 52.8 | 29.2 | 22.4 | 0.0 | Occlusion Deformation Background Clutters |
| Surfer | 376 | 314x236 | 73.9 | 38.6 | 13.4 | 23.2 | 0.0 | Out-of-Plane Rotation Scale Variation Fast Motion In-Plane Rotation Low Resolution |
| CarDark | 393 | 198x149 | 73.7 | 62.9 | 17.4 | 24.5 | 0.0 | Illumination Variation Background Clutters |
| Suv | 945 | 85x64 | 71.9 | 57.9 | 42.6 | 27.4 | 0.0 | Occlusion In-Plane Rotation Out-of-View |
| Dog1 | 1350 | 119x90 | 58.7 | 42.7 | 22.7 | 21.6 | 68.4 | Out-of-Plane Rotation Scale Variation In-Plane Rotation |
| Deer | 71 | 143x81 | 55.7 | 39.9 | 92.7 | 37.1 | 0.0 | Motion Blur Fast Motion In-Plane Rotation Background Clutters |
| Car2 | 913 | 89x67 | 54.2 | 41.0 | 47.2 | 41.4 | 69.8 | Illumination Variation Background Clutters |
| Box | 1161 | 109x81 | 53.6 | 39.1 | 102.3 | 39.7 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Motion Blur In-Plane Rotation Out-of-View Background Clutters |
| BlurBody | 334 | 61x46 | 52.0 | 57.5 | 42.3 | 9.0 | 15.9 | Scale Variation Deformation Motion Blur Fast Motion In-Plane Rotation |
| Twinnings | 472 | 80x60 | 51.5 | 39.5 | 60.2 | 46.2 | 0.0 | Out-of-Plane Rotation Scale Variation |
| Dudek | 1145 | 76x50 | 49.7 | 40.1 | 160.5 | 46.9 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Fast Motion In-Plane Rotation Out-of-View Background Clutters |
| Doll | 3872 | 132x99 | 48.0 | 36.2 | 50.0 | 41.0 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion In-Plane Rotation |
| Sylvester | 1345 | 92x69 | 45.8 | 37.9 | 29.1 | 15.2 | 88.1 | Illumination Variation Out-of-Plane Rotation In-Plane Rotation |
| Mhyang | 1490 | 78x58 | 44.7 | 38.2 | 52.6 | 40.1 | 0.0 | Illumination Variation Out-of-Plane Rotation Deformation Background Clutters |
| Liquor | 1741 | 83x62 | 44.1 | 58.1 | 50.0 | 12.5 | 28.5 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Motion Blur Fast Motion Out-of-View Background Clutters |
| Dog | 127 | 109x74 | 41.3 | 19.8 | 56.5 | 39.7 | 97.6 | Out-of-Plane Rotation Scale Variation Deformation |
| Bird2 | 99 | 162x90 | 40.8 | 35.1 | 77.0 | 44.9 | 0.0 | Out-of-Plane Rotation Occlusion Deformation Fast Motion In-Plane Rotation |
| Car24 | 3059 | 201x151 | 39.8 | 18.8 | 66.9 | 59.6 | 0.0 | Illumination Variation Scale Variation Background Clutters |
| Tiger1 | 349 | 136x102 | 39.7 | 30.5 | 93.2 | 50.3 | 17.0 | Illumination Variation Out-of-Plane Rotation Occlusion Deformation Motion Blur Fast Motion In-Plane Rotation |
| Crossing | 120 | 198x132 | 38.7 | 32.2 | 53.9 | 61.3 | 0.0 | Scale Variation Deformation Background Clutters |
| Girl | 500 | 55x41 | 37.9 | 28.9 | 36.7 | 57.1 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion In-Plane Rotation |
| Skating1 | 400 | 192x108 | 37.6 | 27.6 | 74.2 | 48.9 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Deformation Background Clutters |
| Freeman3 | 460 | 461x307 | 36.6 | 22.7 | 109.3 | 64.5 | 0.0 | Out-of-Plane Rotation Scale Variation In-Plane Rotation Low Resolution |
| MountainBike | 228 | 167x94 | 36.1 | 25.7 | 131.9 | 60.8 | 26.4 | Out-of-Plane Rotation In-Plane Rotation Background Clutters |
| Walking2 | 500 | 103x77 | 36.1 | 27.6 | 46.9 | 41.1 | 43.7 | Scale Variation Occlusion |
| Football1 | 74 | 168x138 | 34.2 | 22.4 | 104.9 | 65.8 | 0.0 | Out-of-Plane Rotation In-Plane Rotation Background Clutters |
| Lemming | 1336 | 129x97 | 33.7 | 28.7 | 95.1 | 40.0 | 72.4 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Fast Motion Out-of-View |
| Skater2 | 435 | 58x48 | 33.2 | 35.8 | 30.9 | 0.0 | 97.5 | Out-of-Plane Rotation Scale Variation Deformation Fast Motion In-Plane Rotation |
| Basketball | 725 | 176x132 | 32.6 | 22.2 | 81.8 | 48.6 | 93.9 | Illumination Variation Out-of-Plane Rotation Occlusion Deformation Background Clutters |
| Human5 | 713 | 306x408 | 32.3 | 23.6 | 241.5 | 67.6 | 0.0 | Scale Variation Occlusion Deformation |
| Freeman1 | 326 | 227x151 | 30.5 | 16.0 | 65.6 | 62.8 | 12.9 | Out-of-Plane Rotation Scale Variation In-Plane Rotation |
| Human7 | 250 | 78x59 | 26.5 | 22.6 | 36.2 | 10.0 | 95.6 | Illumination Variation Scale Variation Occlusion Deformation Motion Blur Fast Motion |
| Human6 | 792 | 244x325 | 24.4 | 19.0 | 141.3 | 71.6 | 16.7 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Fast Motion Out-of-View |
| David2 | 537 | 169x127 | 23.9 | 19.1 | 73.4 | 76.1 | 0.0 | Out-of-Plane Rotation In-Plane Rotation |
| FleetFace | 707 | 86x57 | 23.8 | 28.4 | 105.1 | 39.9 | 79.0 | Out-of-Plane Rotation Scale Variation Deformation Motion Blur Fast Motion In-Plane Rotation |
| Panda | 1000 | 197x147 | 23.7 | 15.3 | 57.6 | 73.8 | 88.0 | Out-of-Plane Rotation Scale Variation Occlusion Deformation In-Plane Rotation Out-of-View Low Resolution |
| Biker | 142 | 502x282 | 23.4 | 16.1 | 85.7 | 75.9 | 72.3 | Out-of-Plane Rotation Scale Variation Occlusion Motion Blur Fast Motion Out-of-View Low Resolution |
| Man | 134 | 121x97 | 22.6 | 22.0 | 39.8 | 77.4 | 0.0 | Illumination Variation |
| Girl2 | 1500 | 118x89 | 22.2 | 17.6 | 147.0 | 71.9 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Motion Blur |
| ClifBar | 472 | 127x95 | 20.6 | 15.2 | 73.7 | 77.3 | 0.0 | Scale Variation Occlusion Motion Blur Fast Motion In-Plane Rotation Out-of-View Background Clutters |
| Tiger2 | 365 | 141x105 | 20.1 | 17.5 | 94.5 | 65.4 | 40.4 | Illumination Variation Out-of-Plane Rotation Occlusion Deformation Motion Blur Fast Motion In-Plane Rotation Out-of-View |
| BlurCar4 | 380 | 64x48 | 19.5 | 16.5 | 276.5 | 80.5 | 0.0 | Motion Blur Fast Motion |
| KiteSurf | 84 | 292x164 | 18.1 | 14.4 | 104.9 | 81.9 | 0.0 | Illumination Variation Out-of-Plane Rotation Occlusion In-Plane Rotation |
| Car1 | 1020 | 85x64 | 17.7 | 8.8 | 94.1 | 71.5 | 80.9 | Illumination Variation Scale Variation Background Clutters Low Resolution |
| Fish | 476 | 70x53 | 17.5 | 15.0 | 149.0 | 82.3 | 0.0 | Illumination Variation |
| Football | 362 | 226x128 | 15.0 | 12.6 | 128.5 | 83.4 | 4.4 | Out-of-Plane Rotation Occlusion In-Plane Rotation Background Clutters |
| Bolt2 | 293 | 165x93 | 14.0 | 9.7 | 107.6 | 83.9 | 33.6 | Deformation Background Clutters |
| Coupon | 327 | 72x54 | 13.2 | 12.0 | 94.8 | 62.3 | 0.0 | Occlusion Background Clutters |
| Singer1 | 351 | 63x35 | 12.6 | 11.9 | 124.6 | 46.9 | 90.6 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion |
| Freeman4 | 283 | 372x248 | 12.4 | 9.7 | 116.4 | 87.6 | 5.0 | Out-of-Plane Rotation Scale Variation Occlusion In-Plane Rotation Low Resolution |
| Skating2-1 | 473 | 83x46 | 12.3 | 22.5 | 54.0 | 3.2 | 96.4 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Fast Motion |
| Vase | 271 | 99x75 | 12.2 | 11.2 | 96.8 | 87.8 | 5.6 | Scale Variation Fast Motion In-Plane Rotation |
| Diving | 215 | 123x69 | 12.1 | 12.1 | 88.8 | 78.0 | 0.0 | Scale Variation Deformation In-Plane Rotation |
| David3 | 252 | 151x113 | 12.0 | 9.2 | 181.6 | 87.6 | 0.0 | Out-of-Plane Rotation Occlusion Deformation Background Clutters |
| Board | 698 | 55x41 | 11.4 | 14.0 | 217.7 | 69.5 | 0.0 | Out-of-Plane Rotation Scale Variation Motion Blur Fast Motion Out-of-View Background Clutters |
| Couple | 140 | 130x98 | 10.8 | 9.2 | 103.0 | 89.2 | 0.0 | Out-of-Plane Rotation Scale Variation Deformation Fast Motion Background Clutters |
| Shaking | 365 | 152x86 | 10.2 | 7.5 | 180.3 | 87.6 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation In-Plane Rotation Background Clutters |
| CarScale | 252 | 310x132 | 10.0 | 9.0 | 89.7 | 88.8 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion Fast Motion In-Plane Rotation |
| Human9 | 305 | 84x63 | 9.9 | 10.6 | 120.5 | 70.7 | 84.5 | Illumination Variation Scale Variation Deformation Motion Blur Fast Motion |
| Toy | 271 | 99x74 | 9.6 | 8.8 | 107.1 | 88.9 | 10.7 | Out-of-Plane Rotation Scale Variation Fast Motion In-Plane Rotation |
| Soccer | 392 | 139x78 | 9.2 | 7.6 | 165.3 | 87.2 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Motion Blur Fast Motion In-Plane Rotation Background Clutters |
| Human8 | 128 | 98x73 | 8.7 | 4.6 | 88.1 | 77.2 | 8.7 | Illumination Variation Scale Variation Deformation |
| Rubik | 1997 | 139x104 | 8.4 | 6.9 | 272.6 | 91.6 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion In-Plane Rotation |
| Trans | 124 | 62x32 | 8.1 | 15.1 | 165.3 | 57.7 | 0.0 | Illumination Variation Scale Variation Occlusion Deformation |
| DragonBaby | 113 | 170x95 | 6.2 | 4.5 | 184.7 | 93.8 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion Motion Blur Fast Motion In-Plane Rotation Out-of-View |
| Woman | 597 | 126x103 | 6.0 | 3.7 | 92.0 | 92.4 | 11.4 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Deformation Motion Blur Fast Motion |
| Human2 | 1128 | 44x58 | 5.9 | 19.2 | 219.3 | 74.0 | 44.4 | Illumination Variation Out-of-Plane Rotation Scale Variation Motion Blur |
| Singer2 | 366 | 110x62 | 4.9 | 5.2 | 196.6 | 90.1 | 0.0 | Illumination Variation Out-of-Plane Rotation Deformation In-Plane Rotation Background Clutters |
| Trellis | 569 | 62x46 | 4.6 | 8.0 | 126.6 | 70.6 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation In-Plane Rotation Background Clutters |
| Human4-2 | 667 | 218x163 | 4.4 | 3.7 | 239.3 | 91.9 | 0.0 | Illumination Variation Scale Variation Occlusion Deformation |
| RedTeam | 1918 | 215x147 | 4.4 | 3.0 | 92.9 | 93.9 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion In-Plane Rotation Low Resolution |
| MotorRolling | 164 | 83x47 | 4.3 | 11.0 | 151.9 | 60.7 | 79.1 | Illumination Variation Scale Variation Motion Blur Fast Motion In-Plane Rotation Background Clutters |
| David | 471 | 72x54 | 3.6 | 3.2 | 153.9 | 95.7 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Deformation Motion Blur In-Plane Rotation |
| Skating2-2 | 473 | 64x35 | 3.2 | 7.1 | 202.8 | 76.7 | 0.2 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Fast Motion |
| Ironman | 166 | 218x92 | 3.0 | 2.3 | 197.6 | 97.0 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Motion Blur Fast Motion In-Plane Rotation Out-of-View Background Clutters |
| Human3 | 1698 | 152x203 | 2.9 | 2.5 | 139.8 | 92.2 | 0.0 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Background Clutters |
| Coke | 291 | 165x124 | 2.4 | 2.1 | 123.0 | 96.6 | 0.0 | Illumination Variation Out-of-Plane Rotation Occlusion Fast Motion In-Plane Rotation |
| Matrix | 100 | 320x135 | 2.0 | 1.3 | 164.7 | 97.0 | 0.0 | Illumination Variation Out-of-Plane Rotation Scale Variation Occlusion Fast Motion In-Plane Rotation Background Clutters |
| Bird1 | 408 | 340x189 | 1.7 | 1.4 | 170.6 | 93.1 | 16.7 | Deformation Fast Motion Out-of-View |
| Jump | 122 | 68x38 | 1.7 | 3.9 | 168.5 | 75.2 | 23.1 | Out-of-Plane Rotation Scale Variation Occlusion Deformation Motion Blur In-Plane Rotation |
| Crowds | 347 | 287x229 | 1.2 | 0.8 | 355.5 | 98.8 | 15.0 | Illumination Variation Deformation Background Clutters |
| Skiing | 81 | 373x210 | 1.2 | 1.2 | 242.4 | 95.0 | 21.2 | Illumination Variation Out-of-Plane Rotation Scale Variation Deformation In-Plane Rotation Low Resolution |
| Bolt | 350 | 257x145 | 1.1 | 0.9 | 247.8 | 96.8 | 0.0 | Out-of-Plane Rotation Occlusion Deformation In-Plane Rotation |
| Car4 | 659 | 60x40 | 1.1 | 1.0 | 164.2 | 96.4 | 0.0 | Illumination Variation Scale Variation |
