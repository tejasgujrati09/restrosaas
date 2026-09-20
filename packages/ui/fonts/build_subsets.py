from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

UNI = "U+0020-007E,U+00A0-00FF,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2022,U+2026,U+2212,U+20B9,U+2190,U+2192"

def build(src, out, limits):
    f = TTFont(src)
    print(out, "has rupee:", 0x20B9 in f.getBestCmap())
    inst = instancer.instantiateVariableFont(f, limits)
    inst.save("_inst.ttf")
    g = TTFont("_inst.ttf")
    opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["kern","liga","tnum","lnum","ccmp","locl"]
    opts.notdef_outline = True; opts.name_IDs = [1,2,3,4,6]; opts.drop_tables += ["DSIG"]
    s = subset.Subsetter(opts); s.populate(unicodes=subset.parse_unicodes(UNI)); s.subset(g)
    g.flavor = "woff2"; g.save(out)

build("manrope_Manrope_5Bwght_5D.ttf", "manrope-latin.woff2", {"wght": (500, 700)})
build("fraunces_Fraunces_5BSOFT_2CWONK_2Copsz_2Cwght_5D.ttf", "fraunces-600-latin.woff2", {"wght": 600, "opsz": 24, "SOFT": 0, "WONK": 0})
