#!/usr/bin/python
# -*- coding: utf-8 -*-
from ghostscript._gsprint import *
from ctypes import *

#  gsapi_new_instance(&minst);
#  gsapi_set_display_callback(minst, callback);
#  gsapi_init_with_args(minst, argc, argv);


def dummy(name, ret=None):
    def callback(*args):
        print name, args[0], args[1], args[2:]
        return ret if ret is not None else 0 
    return callback;


# The caller should not access the image buffer:
#  - before the first sync
#  - between presize and size
#  - after preclose

seenSync = False
inPresize = False
afterPreclose = False

def getImage():
    global seenSync, inPresize, afterPreclose
    if not seenSync or inPresize or afterPreclose:
        return
    if len(sizeDict) == 0:
        return
    length = sizeDict['width'] * sizeDict['raster'] * sizeDict['height']
    raster = sizeDict['raster']
    print 'getImage!', length
    for y in xrange(0, sizeDict['height']):
        data = sizeDict['pimage'][y*raster:(y+1)*raster];
        # at least this works! when using rgb all bytes are 255, white
        # when using cmyk all bytes are 0, white!!! that means, that in the
        # end, something is happening here!
        ffs = len([x for x in data if x != 255 or x !=0])
        if ffs != raster:
            print 'line', y, raster-ffs, data

def sync(*args):
    print 'sync'
    global seenSync
    seenSync = True
    getImage();
    return 0

def page(*args):
    print 'page'
    return 0

def presize(*args):
    print 'presize'
    global inPresize
    inPresize = True
    return 0

sizeDict = dict();

def size(void_p_handle, void_p_device, width, height, raster, format, char_p_pimage):
    print 'size', void_p_handle, void_p_device, width, height, raster,'format:', format, char_p_pimage
    global inPresize, sizeDict
    inPresize = False
    sizeDict['width'] = width;
    sizeDict['height'] = height;
    #raster is byte count of a row.
    sizeDict['raster'] = raster;
    sizeDict['format'] = format;
    sizeDict['pimage'] = char_p_pimage;
    return 0

def preclose(*args):
    print 'preclose'
    global afterPreclose
    afterPreclose = True
    return 0


display_callback = Display_callback_s(
    c_int(sizeof(Display_callback_s)),
    c_int(DISPLAY_VERSION_MAJOR),
    c_int(DISPLAY_VERSION_MINOR),
    c_display_open(dummy('open')),
    c_display_preclose(preclose),
    c_display_close(dummy('close')),
    c_display_presize(presize),
    c_display_size(size),
    c_display_sync(sync),
    c_display_page(page),
    cast(None, c_display_update),
    #c_display_update(dummy('update')),
    cast(None, c_display_memalloc),
    cast(None, c_display_memfree),
    cast(None, c_display_separation)
)

# http://www.ghostscript.com/doc/current/API.htm
args = [
    "(ignored)", # actual value doesn't matter
    "-dNOPAUSE",
    "-dBATCH",
    "-dSAFER",
    #"-dEPSFitPage",
    #"-dEPSCrop",
    #"-sDEVICE=display",
    "-sDisplayHandle=cde",
    "-dDisplayFormat=%d" % (DISPLAY_COLORS_RGB | \
        DISPLAY_DEPTH_8 | DISPLAY_BIGENDIAN | DISPLAY_TOPFIRST | DISPLAY_ALPHA_NONE),
    # "-dDisplayFormat=16#%02x" % for formatting as hex in the string
    # "-dDisplayFormat=16#804", #yields in: 2052L
    "../Recherche/colortransforms.pdf"
    ]
#print ' '.join(args);
instance = new_instance()
set_display_callback(instance, byref(display_callback))
code = init_with_args(instance, args)

if code == 0:
    code = run_string(instance, "systemdict /start get exec", 0);

code1 = exit(instance)
if code == 0 or code == e_Quit:
    code = code1
if code == e_Quit:
    code = 0; # user executed 'quit'

delete_instance(instance)
if not code == 0:
    sys.exit(1)
