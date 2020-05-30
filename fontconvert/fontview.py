#!/usr/bin/env python3

import sys
import re
import json
import unicodedata

# typedef struct {
#   uint16_t bitmapOffset; ///< Pointer into GFXfont->bitmap
#   uint8_t width;         ///< Bitmap dimensions in pixels
#   uint8_t height;        ///< Bitmap dimensions in pixels
#   uint8_t xAdvance;      ///< Distance to advance cursor (x axis)
#   int8_t xOffset;        ///< X dist from cursor pos to UL corner
#   int8_t yOffset;        ///< Y dist from cursor pos to UL corner
# } GFXglyph;
#
# typedef struct {
#   uint8_t *bitmap;  ///< Glyph bitmaps, concatenated
#   GFXglyph *glyph;  ///< Glyph array
#   uint16_t first;   ///< ASCII extents (first char)
#   uint16_t last;    ///< ASCII extents (last char)
#   uint8_t yAdvance; ///< Newline distance (y axis)
# } GFXfont;

class GFX_Glyph:
    def __init__(self, bo, w, h, xa, xo, yo):
        self.bo = bo
        self.w = w
        self.h = h
        self.xa = xa
        self.xo = xo
        self.yo = yo

class GFX_Font:
    def __init__(self, name, bitmap, glyphs, first, last, ya):
        self.name = name
        self.bitmap = bitmap
        self.glyphs = glyphs
        self.first = first
        self.last = last
        self.ya = ya

class GFX_FontParser:
    def __init__(self):
        self._cDecls = {}
        pass

    def parse(self, data):
        stripped = self._stripComments(data)
        return self._parseData(stripped)

    def _stripComments(self, data):
        data = re.sub('/\*.*?\*/', '', data, flags=re.S) # C comments
        data = re.sub('//.*', '', data) # C++ comments
        data = re.sub('#.*', '', data) # CPP directives
        data = re.sub('\s+', ' ', data) # merge whitespace runs
        return data

    def _parseData(self, data):
        for s in re.split(' ?; ?', data):
            s = re.sub('^\s*','',s)
            if self._parseBitmap(s):
                continue
            if self._parseGlyphs(s):
                continue
            if self._parseFont(s):
                return self.font
            raise ValueError("cannot parse statement: `{}`".format(s))

    def _parseBitmap(self, stmt):
        m = re.match('const uint8_t (\w*)\[\w*\] PROGMEM = {\s*(.*)\s*}', stmt, re.S)
        if not m:
            return False
        try:
            self._cDecls[m[1]] = [int(x,0)
                    for x in re.split(" ?, ?", m[2]) if len(x)]
        except Exception as e:
            print("failed to parse stmt=`{}`".format(stmt), file=sys.stderr)
            raise e
        return True

    def _parseGlyphs(self, stmt):
        m = re.match('const GFXglyph (\w*)\[\w*\] PROGMEM = {\s*(.*)\s*}', stmt, re.S)
        if not m:
            return False
        arr = [re.split(' ?, ?',im[1])
                for im in re.finditer('{\s*([^}]*)}', m[2])]
        self._cDecls[m[1]] = [GFX_Glyph(*[int(xe,0) for xe in g])
                for g in arr if len(g)]
        return True

    def _parseFont(self, stmt):
        m = re.match('const GFXfont (\w*) PROGMEM = {\s*(.*?)\s*}', stmt, re.S)
        if not m:
            return False
        name = m[1]
        elements = re.split(' ?, ?', m[2])
        elements = [re.sub('^\(.*?\)', '', e) for e in elements] # strip casting
        bitmap = self._cDecls[elements[0]]
        glyphs = self._cDecls[elements[1]]
        (first, last, ya) = [int(ix,0) for ix in elements[2:5]]
        self.font = GFX_Font(name, bitmap, glyphs, first, last, ya)
        return True

class GFX_FontFormatter:
    """ Emit a GFXfont in C++ header format """

    def __init__(self, **kwargs):
        self._unicode_names = kwargs['unicode_names'] \
                if 'unicode_names' in kwargs else False
        self._break_bmp = kwargs['break_bmp'] \
                if 'break_bmp' in kwargs else False
        self._draw = kwargs['draw'] \
                if 'draw' in kwargs else False
        pass

    def _fmtBitmap(self, font):
        s = "{\n"
        if self._break_bmp:
            glyphEnds = {}
            ch = font.first
            for g in font.glyphs:
                glyphEnds[int(g.bo + ((g.h * g.w) + 7) / 8)] = (g, ch)
                ch += 1
            # Place a clang-format resistant comment after each glyph in the bmp
            for i in range(len(font.bitmap)):
                if (i in glyphEnds):
                    (g, ch) = glyphEnds[i]
                    s += " // 0x{:02X} '{}' ({} x {}) \n\n".format(ch, chr(ch),
                            g.w, g.h)
                    if self._draw:
                        pos = 8 * g.bo
                        for y in range(g.h):
                            s += '      // '
                            for x in range(g.w):
                                bit = font.bitmap[int(pos / 8)]
                                bit = (bit >> (7 - (pos%8))) & 1
                                s += '*' if (bit) else ' '
                                pos += 1
                            s += '\n'
                    s += '\n'
                sep = '' if i == len(font.bitmap) - 1 else ','
                s += '0x{:02X}{}'.format(font.bitmap[i], sep)
        else:
            s += ', '.join(['0x{:02X}'.format(x) for x in font.bitmap])
        s += "};"
        return s

    def _fmtGlyphs(self, font):
        s = '{'
        for i in range(len(font.glyphs)):
            ch = font.first + i
            chChr = chr(ch)

            if self._unicode_names:
                chName = ''
                try:
                    uName = unicodedata.name(chChr)
                    # If it has a uName we can print the char and its name
                    chName += " {}:{}".format(chChr, uName)
                except ValueError:
                    pass
                chComment = "{}".format(chName)
            else:
                prn = ch >= 0x20 and ch <= 0x7e
                chComment = " '{}'".format(chChr) if prn else ""
            comment = "0x{:02X}{}".format(ch, chComment)
            sep = '};' if i == len(font.glyphs)-1 else ','
            g = font.glyphs[i]
            s += '{{{}, {}, {}, {}, {}, {}}}{} // {}\n'.format(
               g.bo, g.w, g.h, g.xa, g.xo, g.yo, sep, comment)
        return s

    def format(self, font):
        approximateBytes = len(font.bitmap) + len(font.glyphs) * 7 + 7

        out = \
"""const uint8_t {0}Bitmaps[] PROGMEM = {1}

const GFXglyph {0}Glyphs[] PROGMEM = {2}

const GFXfont {0} PROGMEM = {{
    (uint8_t *){0}Bitmaps,
    (GFXglyph *){0}Glyphs,
    0x{3:02X}, 0x{4:02X}, {5}
}};

// Approx. {6} bytes
""".format(font.name,
           self._fmtBitmap(font),
           self._fmtGlyphs(font),
           font.first,
           font.last,
           font.ya,
           approximateBytes)
        return out

def main():
    data = ''.join(sys.stdin)
    font = GFX_FontParser().parse(data)
    def encodingExtension(obj):
        if isinstance(obj, GFX_Glyph):
            return {"$GFX_Glyph": obj.__dict__}
        if isinstance(obj, GFX_Font):
            return {"$GFX_Font": obj.__dict__}
        raise TypeError(repr(obj) + " is not JSON serializable")

    if False:
        print(json.dumps(font, default=encodingExtension))

    fmtArgs = {
            "unicode_names": True,
            "break_bmp": True,
            "draw": True,
    }
    formatter = GFX_FontFormatter(**fmtArgs)
    print("{}".format(formatter.format(font)))

if __name__ == "__main__":
    main()

