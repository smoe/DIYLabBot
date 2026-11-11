"""Font-independent pen strokes wrapped onto glass; visual instance annotations."""
import math
import re

# Original single-line glyphs, in a one-unit cap-height coordinate system.
# Polylines describe pen paths, not filled/engraved font outlines.
PATHS = {
    'A': ['0,0 .5,1 1,0', '.2,.4 .8,.4'], 'B': ['0,0 0,1 .65,1 1,.8 .65,.55 0,.55', '.65,.55 1,.3 .8,0 0,0'],
    'C': ['1,.85 .7,1 .2,.9 0,.6 0,.25 .3,0 .8,0 1,.15'],
    'D': ['0,0 0,1 .5,1 1,.7 1,.3 .5,0 0,0'], 'E': ['1,1 0,1 0,0 1,0', '0,.5 .75,.5'],
    'F': ['0,0 0,1 1,1', '0,.55 .8,.55'], 'G': ['1,.8 .7,1 .2,.9 0,.6 0,.25 .3,0 1,0 1,.45 .55,.45'],
    'H': ['0,0 0,1', '1,0 1,1', '0,.5 1,.5'], 'I': ['.1,1 .9,1', '.5,1 .5,0', '.1,0 .9,0'],
    'J': ['0,.2 .2,0 .65,0 .85,.2 .85,1', '.35,1 1,1'], 'K': ['0,0 0,1', '1,1 0,.45 1,0'],
    'L': ['0,1 0,0 1,0'], 'M': ['0,0 0,1 .5,.35 1,1 1,0'], 'N': ['0,0 0,1 1,0 1,1'],
    'O': ['.3,0 .05,.25 0,.65 .25,1 .7,1 1,.7 1,.25 .75,0 .3,0'],
    'P': ['0,0 0,1 .75,1 1,.75 .75,.5 0,.5'], 'Q': ['.3,0 0,.25 0,.75 .3,1 .75,1 1,.7 1,.25 .75,0 .3,0', '.6,.3 1,-.1'],
    'R': ['0,0 0,1 .75,1 1,.75 .75,.5 0,.5', '.55,.5 1,0'],
    'S': ['1,.85 .75,1 .2,1 0,.75 .2,.55 .8,.45 1,.2 .75,0 .2,0 0,.15'],
    'T': ['0,1 1,1', '.5,1 .5,0'], 'U': ['0,1 0,.25 .25,0 .75,0 1,.25 1,1'],
    'V': ['0,1 .5,0 1,1'], 'W': ['0,1 .2,0 .5,.65 .8,0 1,1'], 'X': ['0,1 1,0', '0,0 1,1'],
    'Y': ['0,1 .5,.5 1,1', '.5,.5 .5,0'], 'Z': ['0,1 1,1 0,0 1,0'],
    '0': ['.3,0 0,.25 0,.75 .3,1 .7,1 1,.75 1,.25 .7,0 .3,0', '.2,.15 .8,.85'],
    '1': ['.15,.75 .5,1 .5,0', '.1,0 .9,0'], '2': ['0,.8 .2,1 .75,1 1,.8 .85,.6 0,0 1,0'],
    '3': ['0,1 1,1 .45,.55 .9,.45 1,.2 .7,0 0,0'], '4': ['.8,0 .8,1 0,.35 1,.35'],
    '5': ['1,1 0,1 0,.55 .75,.55 1,.3 .8,0 .1,0'], '6': ['.9,1 .3,.9 0,.5 0,.2 .3,0 .75,0 1,.25 .75,.5 0,.5'],
    '7': ['0,1 1,1 .25,0'], '8': ['.25,.5 0,.75 .25,1 .75,1 1,.75 .75,.5 .25,.5 0,.25 .25,0 .75,0 1,.25 .75,.5'],
    '9': ['1,.5 .25,.5 0,.75 .25,1 .75,1 1,.75 1,.3 .6,0 .1,0'],
    'a': ['.9,.55 .65,.7 .2,.65 0,.35 .15,.05 .6,0 .9,.3', '.9,.7 .9,0'],
    'b': ['0,1 0,0', '0,.5 .35,.7 .8,.6 1,.3 .8,0 .3,0 0,.2'],
    'c': ['1,.6 .7,.7 .2,.6 0,.3 .2,0 .8,0 1,.1'], 'd': ['1,1 1,0', '1,.5 .65,.7 .2,.6 0,.3 .2,0 .7,0 1,.2'],
    'e': ['0,.35 1,.35 .85,.6 .55,.7 .15,.55 0,.3 .2,0 .8,0 1,.1'],
    'f': ['.2,0 .2,.8 .4,1 .8,1', '0,.6 .7,.6'], 'g': ['1,.7 1,-.15 .7,-.3 .2,-.25', '1,.5 .7,.7 .2,.6 0,.3 .2,0 .7,0 1,.2'],
    'h': ['0,1 0,0', '0,.45 .4,.7 .8,.6 1,.4 1,0'], 'i': ['.5,0 .5,.65', '.5,.9 .52,.92'],
    'j': ['.65,.65 .65,-.1 .4,-.3 .1,-.25', '.65,.9 .67,.92'],
    'k': ['0,1 0,0', '.9,.7 0,.3 1,0'], 'l': ['.4,1 .4,.15 .6,0 .85,.05'],
    'm': ['0,0 0,.7', '0,.5 .25,.7 .5,.5 .5,0', '.5,.5 .75,.7 1,.5 1,0'],
    'n': ['0,0 0,.7', '0,.5 .4,.7 .8,.6 1,.4 1,0'],
    'o': ['.25,0 0,.2 0,.5 .25,.7 .75,.7 1,.5 1,.2 .75,0 .25,0'],
    'p': ['0,-.3 0,.7', '0,.5 .35,.7 .8,.6 1,.3 .8,0 .3,0 0,.2'],
    'q': ['1,-.3 1,.7', '1,.5 .7,.7 .2,.6 0,.3 .2,0 .7,0 1,.2'],
    'r': ['0,0 0,.7', '0,.4 .35,.7 .8,.65'],
    's': ['1,.6 .7,.7 .2,.65 0,.45 .2,.35 .8,.25 1,.1 .7,0 .2,0 0,.1'],
    't': ['.35,1 .35,.15 .55,0 .9,.1', '0,.65 .85,.65'],
    'u': ['0,.7 0,.2 .2,0 .65,0 1,.3', '1,.7 1,0'], 'v': ['0,.7 .5,0 1,.7'],
    'w': ['0,.7 .2,0 .5,.5 .8,0 1,.7'], 'x': ['0,.7 1,0', '0,0 1,.7'],
    'y': ['0,.7 .5,0 1,.7', '.5,0 .3,-.3 0,-.25'], 'z': ['0,.7 1,.7 0,0 1,0'],
    '-': ['.15,.4 .85,.4'], '_': ['0,0 1,0'], '+': ['0,.4 1,.4', '.5,.1 .5,.7'],
    '.': ['.45,0 .5,.04'], ',': ['.5,.05 .35,-.15'], ':': ['.5,.15 .52,.17', '.5,.65 .52,.67'],
    '/': ['0,0 1,1'], '=': ['0,.3 1,.3', '0,.6 1,.6'], '(': ['.7,1 .3,.75 .2,.3 .6,0'],
    ')': ['.3,1 .7,.75 .8,.3 .4,0'], 'µ': ['0,.7 0,-.3', '0,.2 .3,0 .8,.1 .8,.7', '.8,.1 1,0'],
    '%': ['0,0 1,1', '0,.7 0,1 .3,1 .3,.7 0,.7', '.7,0 .7,.3 1,.3 1,0 .7,0'],
    '#': ['.25,0 .4,1', '.65,0 .8,1', '0,.3 1,.3', '.1,.7 1,.7'],
    '[': ['.8,1 .2,1 .2,0 .8,0'], ']': ['.2,1 .8,1 .8,0 .2,0'],
    ';': ['.5,.65 .52,.67', '.5,.15 .35,-.1'], '?': ['0,.8 .3,1 .8,1 1,.75 .5,.45 .5,.3', '.5,0 .52,.02'],
    'ß': ['0,0 0,.8 .3,1 .7,1 .8,.75 .4,.55 .8,.45 1,.2 .75,0 .3,0'],
}
for base, accented in [('a','ä'),('o','ö'),('u','ü'),('A','Ä'),('O','Ö'),('U','Ü')]:
    dots = ['.25,.92 .28,.95', '.75,.92 .78,.95'] if base.islower() else ['.25,1.15 .28,1.18', '.75,1.15 .78,1.18']
    PATHS[accented] = PATHS[base]+dots


def validate(label):
    if label is None:
        return None
    if not isinstance(label, dict) or set(label)-{'text','color','height_mm','line_width_mm'} or 'text' not in label:
        raise ValueError('Marker label requires text and optional color/height_mm/line_width_mm')
    text = label['text']
    if not isinstance(text,str) or not text.strip() or len(text)>80 or len(text.split('\n'))>3:
        raise ValueError('Marker labels require 1–80 characters on at most three lines')
    for char in text:
        if char not in PATHS and char not in {' ', '\n'}:
            raise ValueError('Unsupported portable marker character: '+repr(char))
    color = label.get('color','#18242b')
    if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):
        raise ValueError('Marker ink color must be #rrggbb')
    height, width = label.get('height_mm',5), label.get('line_width_mm',.28)
    for value, lo, hi in [(height,2,12),(width,.1,1)]:
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('Marker height/line width must be finite dimensions within their supported ranges')
    return {'text':text, 'color':color, 'height_mm':height, 'line_width_mm':width}


def build(spec,p):
    label = validate(spec.get('label'))
    if label is None:
        return [], None
    family = spec['item']['family']
    if family == 'funnel':
        low, high = p['stem_length']+p['bowl_height']*.2, p['height']-p['bowl_height']*.15
        def radius(z):
            return p['stem_radius']+(p['outer_radius']-p['stem_radius'])*(z-p['stem_length'])/p['bowl_height']
    else:
        low = p['bottom']+2
        high = p.get('body_height',p['height']-p.get('spout_depth',0))-2
        def radius(z):
            return p['outer_radius']
    lines = label['text'].split('\n')
    longest = max(len(line) for line in lines)
    center = (low+high)/2
    height = min(label['height_mm'], (high-low)/(len(lines)*1.6), radius(center)*1.6/(longest*.78))
    if height < 1.5:
        raise ValueError('Marker label does not fit this vessel; shorten the text or add a line break')
    width = min(label['line_width_mm']*height/label['height_mm'],height*.16)
    strokes = []
    def surface(x,z):
        r = radius(z)
        angle = x/r
        return [r*math.sin(angle), -r*math.cos(angle), z]
    for row, line in enumerate(lines):
        x0 = -(max(0,len(line)-1)*.78+.6)*height/2
        z0 = center+((len(lines)-1)/2-row)*height*1.5-height*.4
        for index, char in enumerate(line):
            if char==' ':
                continue
            for path in PATHS[char]:
                points = [tuple(map(float,point.split(','))) for point in path.split()]
                for a,b in zip(points,points[1:]):
                    ax,az = x0+(index*.78+a[0]*.6+a[1]*.04)*height,z0+a[1]*height
                    bx,bz = x0+(index*.78+b[0]*.6+b[1]*.04)*height,z0+b[1]*height
                    # Short chords follow both cylindrical and conical glass surfaces.
                    chord = min(4, math.sqrt(2*radius(center)*width))
                    count = max(1,math.ceil(math.hypot(bx-ax,bz-az)/chord))
                    for step in range(count):
                        first = surface(ax+(bx-ax)*step/count,az+(bz-az)*step/count)
                        last = surface(ax+(bx-ax)*(step+1)/count,az+(bz-az)*(step+1)/count)
                        length = math.dist(first,last)
                        if length < 1e-9:
                            continue
                        strokes.append({'kind':'cylinder','origin':first, 'radius':width/2, 'height':length,
                                        'axis':[(b-a)/length for a,b in zip(first,last)]})
    return strokes, {**label,'effective_height_mm':height, 'effective_line_width_mm':width,
                     'style':'permanent_marker', 'geometry_role':'marker_ink', 'display_only':True,
                     'stroke_font':'portable_pen_paths/1', 'surface_center_mm':[0,-radius(center),center]}
