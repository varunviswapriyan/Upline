import struct


def read_shp(path, mode="auto"):
    with open(path, "rb") as f:
        data = f.read()
    shp_type = struct.unpack("<i", data[32:36])[0]
    out = []
    pos = 100
    n = len(data)
    while pos + 8 <= n:
        clen = struct.unpack(">i", data[pos + 4:pos + 8])[0] * 2
        rec = data[pos + 8:pos + 8 + clen]
        pos += 8 + clen
        t = struct.unpack("<i", rec[:4])[0]
        if t == 0:
            out.append(None)
        elif t in (1, 11, 21):
            out.append(struct.unpack("<2d", rec[4:20]))
        elif t in (3, 13, 23, 5, 15, 25):
            nparts, npts = struct.unpack("<2i", rec[36:44])
            parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts])) + [npts]
            p0 = 44 + 4 * nparts
            pts = struct.unpack(f"<{2 * npts}d", rec[p0:p0 + 16 * npts])
            geo = []
            for a, b in zip(parts[:-1], parts[1:]):
                geo.append([(pts[2 * i], pts[2 * i + 1]) for i in range(a, b)])
            out.append(geo)
        else:
            out.append(None)
    return shp_type, out
