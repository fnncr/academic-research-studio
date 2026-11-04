"""Bounded PNG subset: 8-bit RGB/RGBA, no interlace or external resources."""
import base64
import struct
import zlib

MAX_BYTES = 512 * 1024


def read_png(value):
    try:
        data = base64.b64decode(value, validate=True)
        if len(data) > MAX_BYTES or data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError()
        offset=8; chunks=[]; compressed=[]; width=height=channels=0; ended=False
        while offset < len(data):
            if offset+12>len(data): raise ValueError()
            size=struct.unpack('>I',data[offset:offset+4])[0]; kind=data[offset+4:offset+8]
            end=offset+12+size
            if end>len(data): raise ValueError()
            payload=data[offset+8:offset+8+size]
            if zlib.crc32(kind+payload)&0xffffffff != struct.unpack('>I',data[end-4:end])[0]: raise ValueError()
            if not chunks and kind!=b'IHDR': raise ValueError()
            if kind==b'IHDR':
                if chunks or size!=13: raise ValueError()
                width,height,depth,color,comp,filtering,interlace=struct.unpack('>IIBBBBB',payload)
                if not 0<width<=4096 or not 0<height<=4096 or width*height>4_000_000 or depth!=8 or color not in (2,6) or comp or filtering or interlace: raise ValueError()
                channels=3 if color==2 else 4
            elif kind==b'IDAT':
                if ended: raise ValueError()
                compressed.append(payload)
            elif kind==b'IEND':
                if size or end!=len(data) or not compressed: raise ValueError()
                chunks.append(kind); offset=end; break
            elif kind[0]&32:  # Ancillary chunks are preserved, never interpreted.
                if compressed: ended=True
            else: raise ValueError()
            chunks.append(kind); offset=end
        if not chunks or chunks[-1]!=b'IEND': raise ValueError()
        stride=width*channels+1; expected=stride*height
        decoder=zlib.decompressobj(); raw=decoder.decompress(b''.join(compressed),expected+1)
        if len(raw)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail: raise ValueError()
        if any(raw[row*stride]>4 for row in range(height)): raise ValueError()
        return data,width,height
    except (ValueError,struct.error,zlib.error,IndexError):
        raise ValueError('Use a valid noninterlaced 8-bit RGB/RGBA PNG up to 512 KiB and 4 million pixels') from None
