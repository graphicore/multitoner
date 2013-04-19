#!/usr/bin/python
# -*- coding: utf-8 -*-

# Ghostscript frontend which provides a graphical window
# using PyGtk.  Load time linking to libgs.so with python-ghostscript
# c-bindings
# 
# this is a python port from dxmain.c by artifex
# dxmain.c provides the "gs" command on linux shell
#

from __future__ import with_statement, division

import ghostscript._gsprint as gs
import ctypes as c

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

#ubuntu installed package: python-gi-cairo, not shure now if its needed
# fails when being used: from gi.repository import cairo
# using regular bindings:
import cairo
import Image

import sys
from array import array

start_string = "systemdict /start get exec\n"

#####################################################################
# stdio functions

# this looks like not needed in python. a simple dict would do it
class Stdin_buf (c.Structure):
    _fields_ = [
        ('buf', c.POINTER(c.c_char)), # not shure if this is right, in c it was: char *buf;
        # length of buffer
        ('len', c.c_int),
        # number of characters returned
        ('count', c.c_int),
    ]

# handler for reading non-blocking stdin
def read_stdin_handler(channel, condition, inputBuffer):
    """
    where channel is fd, the file descriptor;
    cb_condition is the condition that triggered the signal;
    and, ... are the zero or more arguments that were passed to the
    GLib.io_add_watch() function.
    
    If the callback function returns False it will be automatically removed
    from the list of event sources and will not be called again. If it
    returns True it will be called again when the condition is matched.
    
    """
    if condition & GLib.IOCondition.PRI:
        print ('input exception')
        inputBuffer.count = 0 #EOF
    elif condition & GLib.IOCondition.IN:
        try:
            data = channel.readline(inputBuffer.len)
        except Exception as exception:
            print (exception) # dunno yet what exceptions occur here.
            inputBuffer.count = -1 # this keeps the loop going
        else:
            if not data:
                inputBuffer.count = 0
            else:
                inputBuffer.count = len(data)
                # copy data to inputBuffer.buf
                c.memmove(inputBuffer.buf, c.c_char_p(data), inputBuffer.count)
    else:
        print ('input condition unknown')
        inputBuffer.count = 0 #EOF
    return True;

# callback for reading stdin
# static int gsdll_stdin(void *instance, char *buf, int len);
def _gsdll_stdin(instance, buf, length):
    inputBuffer = Stdin_buf(buf, length, -1) # buf, len, count
    
    #TODO: see, here is the stdin coming into play
    # for python, the straight way would be sys.stdin I guess
    channel = sys.stdin
    # (fd, condition, callback, user_data=None) -> source id
    # callable receives (fd, condition, user_data)
    # Arranges for the fd to be monitored by the main loop for the
    # specified condition.
    # fd : a Python file object or an integer file descriptor ID
    input_tag = GLib.io_add_watch(
        channel,
        # condition is a combination of GLib.IOCondition.IN, GLib.IOCondition.OUT,
        # GLib.IOCondition.PRI, GLib.IOCondition.ERR and GLib.IOCondition.HUP.
        (GLib.IOCondition.IN | GLib.IOCondition.PRI | GLib.IOCondition.ERR | GLib.IOCondition.HUP),
        read_stdin_handler,
        inputBuffer
    )
    while inputBuffer.count < 0:
        # The Gtk.main_iteration_do() function runs a single iteration of
        # the main loop. If block is True block until an event occurs. 
        Gtk.main_iteration_do(True)
    GLib.source_remove(input_tag)
    return inputBuffer.count

gsdll_stdin = gs.c_stdstream_call_t(_gsdll_stdin)


def _gsdll_stdout(instance, str, length):
    sys.stdout.write(str[:length])
    sys.stdout.flush()
    return length

gsdll_stdout = gs.c_stdstream_call_t(_gsdll_stdout)


def _gsdll_stderr(instance, str, length):
    sys.stderr.write(str[:length])
    sys.stderr.flush()
    return length

gsdll_stderr = gs.c_stdstream_call_t(_gsdll_stderr)


#####################################################################
# dll display device

class ImageDeviceN(object):
    """
        a dict would be sufficient here, but a class documents better
        what propertires are going to be used
    """
    used = 0 # int, non-zero if in use
    visible = True # bool
    name = None # char name[64]
    cyan = 0 # int
    magenta = 0 # int
    yellow = 0 # int
    black = 0 # int
    menu = None # int, non-zero if menu item added to system menu

IMAGE_DEVICEN_MAX = 8

class ImageData(object):
    """
        a dict would be sufficient here, but a class documents better
        what propertires are going to be used
    """
    def __init__ (self):
        self.separation = [None] * IMAGE_DEVICEN_MAX
        self.devicen = [ImageDeviceN() for i in range(0, IMAGE_DEVICEN_MAX)]
        
    handle = None # void *handle
    device = None # void *device
    window = None # GtkWidget *window;
    vbox = None # GtkWidget *vbox;
    cmyk_bar = None # GtkWidget *cmyk_bar;
    #separation =  # GtkWidget *separation[IMAGE_DEVICEN_MAX];
    show_as_gray = None # GtkWidget *show_as_gray;
    scroll = None # GtkWidget *scroll;
    darea = None # GtkWidget *darea;
    buf = None # guchar *buf;
    width = None # gint width;
    height = None # gint height;
    rowstride = None # gint rowstride;
    format = None # unsigned int format;
    devicen_gray = False # bool devicen_gray; true if a single separation should be shown gray
    #devicen = [] # IMAGE_DEVICEN devicen[IMAGE_DEVICEN_MAX];
    rgbbuf = None # guchar *rgbbuf; used when we need to convert raster format
     # IMAGE *next; # no need for this as we use the images dict for lookup

images = {};

def image_find(handle, device):
    try:
        return images[(handle, device)]
    except KeyError:
        return None

def window_draw(widget, cr, img):
    """
    widget is a gtk_drawing_area_new and should be equal to img.darea
    this callback is called via: img.darea.connect('draw', window_draw, img)
    """
    print 'window_draw' #dbg
    if img and img.window and img.buf:
        color = img.format & gs.DISPLAY_COLORS_MASK;
        depth = img.format & gs.DISPLAY_DEPTH_MASK;
        
        bgcol = widget.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
        
        cr.set_source_rgba(bgcol.red, bgcol.blue, bgcol.green, bgcol.alpha)
        # there is no cr.set_source_color
        # cr.set_source_color(widget.get_style_context()
        #     .get_background_color(Gtk.StateFlags.NORMAL))
        
        cr.paint()
        
    #    pixbuf = None
    #    # the declaration of pixbuf is mostly the same! dunno why it was made like this
    #    if color == gs.DISPLAY_COLORS_NATIVE:
    #        if depth == gs.DISPLAY_DEPTH_8 and img.rgbbuf:
    #            print 'a'
    #            # https://developer.gnome.org/gdk-pixbuf/stable/gdk-pixbuf-Image-Data-in-Memory.html#gdk-pixbuf-new-from-data
    #            pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                GdkPixbuf.Colorspace.RGB, False, 8,
    #                img.width, img.height, img.width*3,
    #                None, None)
    #        elif depth == gs.DISPLAY_DEPTH_16 and img.rgbbuf:
    #            print 'b'
    #            pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                GdkPixbuf.Colorspace.RGB, False, 8,
    #                img.width, img.height, img.width*3,
    #                None, None)
    #    elif color == gs.DISPLAY_COLORS_GRAY:
    #        if depth == gs.DISPLAY_DEPTH_8 and img.rgbbuf:
    #            print 'c'
    #            pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                GdkPixbuf.Colorspace.RGB, False, 8,
    #                img.width, img.height, img.width*3,
    #                None, None)
    #    elif color == gs.DISPLAY_COLORS_RGB:
    #        if depth == gs.DISPLAY_DEPTH_8:
    #            if img.rgbbuf:
    #                print 'd'
    #                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                    GdkPixbuf.Colorspace.RGB, False, 8,
    #                    img.width, img.height, img.width*3,
    #                    None, None)
    #            else:
    #                print 'e'
    #                # img.buf has no 'length' thats a problem here
    #                # this usually wouldn't happen anymore, an img.rgbbuf
    #                # is created in _display_size and filled in _display_sync
    #                # now
    #                byte_array = array('B', img.buf[0: img.height * img.rowstride])
    #                pixbuf = GdkPixbuf.Pixbuf.new_from_data(byte_array,
    #                    GdkPixbuf.Colorspace.RGB, False, 8,
    #                    img.width, img.height, img.rowstride,
    #                    None, None)
    #    elif color == gs.DISPLAY_COLORS_CMYK:
    #        if (depth == gs.DISPLAY_DEPTH_1 or depth == gs.DISPLAY_DEPTH_8) and img.rgbbuf:
    #            print 'f'
    #            pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                GdkPixbuf.Colorspace.RGB, False, 8,
    #                img.width, img.height, img.width*3,
    #                None, None)
    #    elif color == gs.DISPLAY_COLORS_SEPARATION:
    #        if depth == gs.DISPLAY_DEPTH_8 and img.rgbbuf:
    #            print 'g'
    #            pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
    #                GdkPixbuf.Colorspace.RGB, False, 8,
    #                img.width, img.height, img.width*3,
    #                None, None)
        
        # help(cr)
        # see, looks like there is help:
        # http://stackoverflow.com/questions/10270795/drawing-in-pygobject-python3
        # http://stackoverflow.com/questions/10270080/how-to-draw-a-gdkpixbuf-using-gtk3-and-pygobject
        
        if img.rgbbuf:
            
            #data_array = array('B', img.buf[0: img.height * img.rowstride])
            #pil_image = Image.frombuffer('RGB', (img.width, img.height),  data_array, "raw", "RGB", img.rowstride, 1)
            
            #pil_image.save("pfffffffffffffffffffffffffffffff", "png")
            

            cairo_surface = cairo.ImageSurface.create_for_data(img.rgbbuf, cairo.FORMAT_RGB24, img.width, img.height, img.width * 4)
            cr.set_source_surface(cairo_surface, 0, 0)
            #cr.set_source_pixbuf(pixbuf, 0, 0)
        cr.paint()
    return True

def window_destroy(widget, img):
    del img.window
    del img.scroll
    del img.darea
    
def widget_delete(widget, *args):
    widget.hide_on_delete()

def window_create(img):
    """ Create a gtk window """
    print 'window_create' #dbg
    img.window = Gtk.Window(Gtk.WindowType.TOPLEVEL)
    img.window.set_title("python gs");
    
    img.vbox = Gtk.Box(Gtk.Orientation.VERTICAL, 0)
    img.vbox.set_homogeneous(False)
    
    img.window.add(img.vbox)
    img.vbox.show()

    img.darea = Gtk.DrawingArea()
    img.darea.show()
    
    img.scroll = Gtk.ScrolledWindow(None, None)
    img.scroll.show()
    
    img.scroll.set_policy(Gtk.PolicyType.ALWAYS, Gtk.PolicyType.ALWAYS)
    img.scroll.add_with_viewport(img.darea)
    img.vbox.pack_start(img.scroll, True, True, 0)
    
    img.darea.connect('draw', window_draw, img)
    img.window.connect('destroy', window_destroy, img)
    img.window.connect('delete-event', widget_delete)
    
    # do not show img->window until we know the image size

def window_resize(img):
    img.darea.set_size_request(img.width, img.height)
    visible = img.window.get_visible()
    if not visible:
        # We haven't yet shown the window, so set a default size
        # which is smaller than the desktop to allow room for
        # desktop toolbars, and if possible a little larger than
        # the image to allow room for the scroll bars.
        # We don't know the width of the scroll bars, so just guess.
        img.window.set_default_size(
            min(Gdk.Screen.width()-96, img.width+24),
            min(Gdk.Screen.height()-96, img.height+24)
        )

def window_separation(img, sep):
    img.devicen[sep].visible = not img.devicen[sep].visible
    _display_sync(img.handle, img.device)

def get_signal_separation(sep):
    def signal_sep_i(widget, img):
        window_separation(img, sep)
    return signal_sep_i

def window_add_button(img, label, callback):
    w = Gtk.CheckButton.new_with_label(label or '')
    img.cmyk_bar.pack_start(w, False, False, 5)
    w.set_active(True)
    w.connect('clicked', callback, img)
    w.show()
    return w

def signal_show_as_gray(widget, img):
    img.devicen_gray = not img.devicen_gray
    _display_sync(img.handle, img.device)

def _display_open(handle, device):
    """ New device has been opened """
    print '_display_open' #dbg
    img = ImageData()
    # add to list
    images[(handle, device)] = img
    # remember device and handle
    img.handle = handle
    img.device = device
    # create window
    window_create(img);
    Gtk.main_iteration_do(False)
    return 0;

def _display_preclose(handle, device):
    print '_display_preclose' #dbg
    img = image_find(handle, device)
    if img is None:
        return -1

    Gtk.main_iteration_do(False)

    img.buf = None
    img.width = 0
    img.height = 0
    img.rowstride = 0
    img.format = 0

    img.window.destroy()
    img.window = None
    img.scroll = None
    img.darea = None
    img.rgbbuf = None

    Gtk.main_iteration_do(False)

    return 0;

def _display_close(handle, device):
    print '_display_close' #dbg
    img = image_find(handle, device)
    if img is None:
        return -1
    # remove from list
    del images[(handle, device)]
    return 0;

def _display_presize(handle, device, width, height, raster, format):
    print '_display_presize' #dbg
    # Assume everything is OK.
    # It would be better to return e_rangecheck if we can't
    # support the format.
    return 0;

def _display_size(handle, device, width, height, raster, format, pimage):
    print '_display_size' #dbg
    img = image_find(handle, device)
    if img is None:
        return -1

    img.rgbbuf = None

    img.width = width
    img.height = height
    img.rowstride = raster
    img.buf = pimage
    img.format = format

    # Reset separations
    for i in range(0, IMAGE_DEVICEN_MAX):
        img.devicen[i].used = 0
        img.devicen[i].visible = True
        img.devicen[i].name = None
        img.devicen[i].cyan = 0
        img.devicen[i].magenta = 0
        img.devicen[i].yellow = 0
        img.devicen[i].black = 0

    color = img.format & gs.DISPLAY_COLORS_MASK
    depth = img.format & gs.DISPLAY_DEPTH_MASK
    
    if color == gs.DISPLAY_COLORS_NATIVE:
        if depth == gs.DISPLAY_DEPTH_8:
            # 'B' is unsigned char
            # filled with zeros
            # need to convert to 24RGBX
            img.rgbbuf = array('B', [0] * (width * height * 4) )
        elif depth == gs.DISPLAY_DEPTH_16:
             # need to convert to 24RGBX
            img.rgbbuf = array('B', [0] * (width * height * 4) )
        else:
            return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_GRAY:
        if depth == gs.DISPLAY_DEPTH_8:
             # need to convert to 24RGBX
            img.rgbbuf = array('B', [0] * (width * height * 4) )
        else:
            return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_RGB:
        if depth == gs.DISPLAY_DEPTH_8:
            if (img.format & gs.DISPLAY_ALPHA_MASK) == gs.DISPLAY_ALPHA_NONE \
                and (img.format & gs.DISPLAY_ENDIAN_MASK) == gs.DISPLAY_BIGENDIAN:
                # will convert here, too. the c version did not need to!
                # need to convert to 24RGBX
                img.rgbbuf = array('B', [0] * (width * height * 4) )
            else:
                # need to convert to 24RGBX
                img.rgbbuf = array('B', [0] * (width * height * 4) )
        else:
            return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_CMYK:
        if (depth == gs.DISPLAY_DEPTH_1) or (depth == gs.DISPLAY_DEPTH_8):
            # need to convert to 24RGB
            img.rgbbuf = array('B', [0] * (width * height * 4) )
            # We already know about the CMYK components
            img.devicen[0].used = 1
            img.devicen[0].cyan = 65535
            img.devicen[0].name = 'Cyan'
            
            img.devicen[1].used = 1
            img.devicen[1].magenta = 65535
            img.devicen[1].name = 'Magenta'
            
            img.devicen[2].used = 1
            img.devicen[2].yellow = 65535
            img.devicen[2].name = 'Yellow'

            img.devicen[3].used = 1
            img.devicen[3].black = 65535
            img.devicen[3].name = 'Black'
        else:
            return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_SEPARATION:
        # we can't display this natively
        # we will convert it just before displaying
        if depth != gs.DISPLAY_DEPTH_8:
            return gs.e_rangecheck # not supported
        img.rgbbuf = array('B', [0] * (width * height * 4) )
    
    if color == gs.DISPLAY_COLORS_CMYK or color == gs.DISPLAY_COLORS_SEPARATION:
        if not isinstance(img.cmyk_bar, Gtk.Widget):
            # add bar to select separation
            img.cmyk_bar = Gtk.Box(Gtk.Orientation.HORIZONTAL, 0)
            img.cmyk_bar.set_homogeneous(False)
            img.vbox.pack_start(img.cmyk_bar, False, False, 0)
            for i in range(0, IMAGE_DEVICEN_MAX):
                img.separation[i] = window_add_button(img, img.devicen[i].name, get_signal_separation(i))
            
            
            img.show_as_gray = Gtk.CheckButton.new_with_label('Show as Gray')
            img.cmyk_bar.pack_end(img.show_as_gray, False, False, 5)
            img.show_as_gray.set_active(False)
            img.show_as_gray.connect('clicked', signal_show_as_gray, img)
            img.show_as_gray.show()
        img.cmyk_bar.show()
    else:
        if isinstance(img.cmyk_bar, Gtk.Widget):
            img.cmyk_bar.hide()
    window_resize(img)
    
    visible = img.window.get_visible()
    if not visible:
        img.window.show_all()

    Gtk.main_iteration_do(False)
    return 0

def _display_sync(handle, device):
    print '_display_sync' #dbg
    img = image_find(handle, device)
    if img is None:
        return -1
    
    color = img.format & gs.DISPLAY_COLORS_MASK
    depth = img.format & gs.DISPLAY_DEPTH_MASK
    endian = img.format & gs.DISPLAY_ENDIAN_MASK
    native555 = img.format & gs.DISPLAY_555_MASK
    alpha = img.format & gs.DISPLAY_ALPHA_MASK

    if (color == gs.DISPLAY_COLORS_CMYK) or (color == gs.DISPLAY_COLORS_SEPARATION):
        #check if separations have changed
        for i in range(0, IMAGE_DEVICEN_MAX):
            label = img.separation[i].get_label()
            if not img.devicen[i].used:
                img.separation[i].hide()
            elif img.devicen[i].name != label:
                # text has changed, update it
                img.separation[i].set_label(img.devicen[i].name)
                img.separation[i].show()
    
    # some formats need to be converted for use by GdkRgb
    if color == gs.DISPLAY_COLORS_NATIVE:
        if depth == gs.DISPLAY_DEPTH_16:
            if endian == gs.DISPLAY_LITTLEENDIAN:
                if native555 == gs.DISPLAY_NATIVE_555:
                    # BGR555
                    
                    rgbBufIdx = 0
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        assert rgbBufIdx == idx * 4
                        if idx % img.width is 0 and idx is not 0:
                            bufIdx += stride
                        w = img.buf[bufIdx] + (img.buf[bufIdx+1] << 8)
                        
                        value = (w >> 10) & 0x1f #red
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = (w >> 5) & 0x1f #green
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = w & 0x1f #blue
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 2
                        
                        bufIdx += 2
                else:
                    # BGR565
                    rgbBufIdx = 0
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        assert rgbBufIdx == idx * 4
                        if idx % img.width is 0 and idx is not 0:
                            bufIdx += stride
                        w = img.buf[bufIdx] + (img.buf[bufIdx+1] << 8)
                        
                        value = (w >> 11) & 0x1f #red
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = (w >> 5) & 0x3f # green
                        img.rgbbuf[rgbBufIdx] = (value << 2) + (value >> 4)
                        rgbBufIdx += 1
                        
                        value = w & 0x1f # blue
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 2
                        
                        bufIdx += 2
            else:
                if native555 == gs.DISPLAY_NATIVE_555:
                    # RGB555
                    rgbBufIdx = 0
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        assert rgbBufIdx == idx * 4
                        if idx % img.width is 0 and idx is not 0:
                            bufIdx += stride
                        w = img.buf[bufIdx+1] + (img.buf[bufIdx] << 8)
                        
                        value = (w >> 10) & 0x1f #red
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = (w >> 5) & 0x1f # green
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = w & 0x1f # blue
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 2
                        
                        bufIdx += 2
                else:
                    # RGB565
                    rgbBufIdx = 0
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        assert rgbBufIdx == idx * 4
                        if idx % img.width is 0 and idx is not 0:
                            bufIdx += stride
                        w = img.buf[bufIdx+1] + (img.buf[bufIdx] << 8)
                        
                        value = (w >> 11) & 0x1f # red
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 1
                        
                        value = (w >> 5) & 0x3f # green
                        img.rgbbuf[rgbBufIdx] = (value << 2) + (value >> 4)
                        rgbBufIdx += 1
                        
                        value = w & 0x1f # blue
                        img.rgbbuf[rgbBufIdx] = (value << 3) + (value >> 2)
                        rgbBufIdx += 2
                        
                        bufIdx += 2
        if depth == gs.DISPLAY_DEPTH_8:
            # palette of 96 colors */
            color = [[0,0,0]] * 96
            one = 255 // 3
            for i in range(0, 96):
                # 0->63 = 00RRGGBB, 64->95 = 010YYYYY
                if i < 64:
                    color[i][0] = ((i & 0x30) >> 4) * one # r
                    color[i][1] = ((i & 0x0c) >> 2) * one # g
                    color[i][2] = (i & 0x03) * one        # b
                else:
                    value = i & 0x1f
                    value = (value << 3) + (value >> 2)
                    color[i][0] = color[i][1] = color[i][2] = value
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - img.width
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                w = img.buf[bufIdx]
                img.rgbbuf[rgbBufIdx] = color[w][0] # r
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = color[w][1] # g
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = color[w][2] # b
                rgbBufIdx += 2
                
                bufIdx += 1
    elif color == gs.DISPLAY_COLORS_GRAY:
        if depth == gs.DISPLAY_DEPTH_8:
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - img.width
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                w = img.buf[bufIdx]
                
                img.rgbbuf[rgbBufIdx] = w # r
                rgbBufIdx += 1
                
                img.rgbbuf[rgbBufIdx] = w # g
                rgbBufIdx += 1
                
                img.rgbbuf[rgbBufIdx] = w # b
                rgbBufIdx += 2
                
                bufIdx += 1
    elif color == gs.DISPLAY_COLORS_RGB:
        if depth == gs.DISPLAY_DEPTH_8 and (
                alpha == gs.DISPLAY_ALPHA_FIRST or alpha == gs.DISPLAY_UNUSED_FIRST
            ) and endian == gs.DISPLAY_BIGENDIAN:
            # Mac format
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - (img.width * 4)
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                # img.buf[idx] x = filler
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # r
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # g
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 3] # b
                rgbBufIdx += 2
                
                bufIdx += 4
        elif depth == gs.DISPLAY_DEPTH_8 and endian == gs.DISPLAY_LITTLEENDIAN:
            if alpha == gs.DISPLAY_UNUSED_LAST or alpha == gs.DISPLAY_ALPHA_LAST:
                #Windows format + alpha = BGRx
                rgbBufIdx = 0
                bufIdx = 0
                stride = img.rowstride - (img.width * 4)
                for idx in range(0, img.height * img.width):
                    assert rgbBufIdx == idx * 4
                    if idx % img.width is 0 and idx is not 0:
                        bufIdx += stride
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # r
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # g
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx    ] # b
                    rgbBufIdx += 2
                    
                    bufIdx += 4
            elif alpha == gs.DISPLAY_UNUSED_FIRST or alpha == gs.DISPLAY_ALPHA_FIRST:
                # xBGR
                rgbBufIdx = 0
                bufIdx = 0
                stride = img.rowstride - (img.width * 4)
                for idx in range(0, img.height * img.width):
                    assert rgbBufIdx == idx * 4
                    if idx % img.width is 0 and idx is not 0:
                        bufIdx += stride
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 3] # r
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # g
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # b
                    rgbBufIdx += 2
                    
                    bufIdx += 4
            else:
                # Windows BGR24
                rgbBufIdx = 0
                bufIdx = 0
                stride = img.rowstride - (img.width * 3)
                for idx in range(0, img.height * img.width):
                    assert rgbBufIdx == idx * 4
                    if idx % img.width is 0 and idx is not 0:
                        bufIdx += stride
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # r
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # g
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = img.buf[bufIdx    ] # b
                    rgbBufIdx += 2
                    
                    bufIdx += 3
        elif depth == gs.DISPLAY_DEPTH_8 and alpha == gs.DISPLAY_ALPHA_NONE \
            and endian == gs.DISPLAY_BIGENDIAN:
            #just bgr, but we need the buffer anyways
            print('standard conversion')
            rgbBufIdx = 0
            
            #for y in range(0, img.height):
            #    bufIdx = y * img.rowstride
            #    for x in range(0, img.width):
            #        img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # r
            #        rgbBufIdx += 1
            #        img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # g
            #        rgbBufIdx += 1
            #        img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 0] # b
            #        rgbBufIdx += 2
            #        bufIdx += 3
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - (img.width * 3)
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 2] # r
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 1] # g
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = img.buf[bufIdx + 0] # b
                rgbBufIdx += 2
                bufIdx += 3
    elif color == gs.DISPLAY_COLORS_CMYK:
        if depth == gs.DISPLAY_DEPTH_8:
            # Separations
            vc = img.devicen[0].visible
            vm = img.devicen[1].visible
            vy = img.devicen[2].visible
            vk = img.devicen[3].visible
            vall = vc and vm and vy and vk
            show_gray = (vc + vm + vy + vk == 1) and img.devicen_gray
            
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - (img.width * 4)
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                cyan    = img.buf[bufIdx    ]
                magenta = img.buf[bufIdx + 1]
                yellow  = img.buf[bufIdx + 2]
                black   = img.buf[bufIdx + 3]
                if not vall:
                    if not vc:
                        cyan = 0
                    if not vm:
                        magenta = 0
                    if  not vy:
                        yellow = 0
                    if not vk:
                        black = 0
                    if show_gray:
                        black += cyan + magenta + yellow
                        cyan = magenta = yellow = 0
                
                img.rgbbuf[rgbBufIdx] = (255-yellow)    * (255-black) // 255 # r
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = (255-magenta) * (255-black) // 255 # g
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = (255-cyan)  * (255-black) // 255 # b
                rgbBufIdx += 2
                
                bufIdx += 4
        elif depth == gs.DISPLAY_DEPTH_1:
            # Separations
            vc = img.devicen[0].visible
            vm = img.devicen[1].visible
            vy = img.devicen[2].visible
            vk = img.devicen[3].visible
            vall = vc and vm and vy and vk
            show_gray = (vc + vm + vy + vk == 1) and img.devicen_gray
            
            rgbBufIdx = 0
            for y in range(0, img.height):
                bufIdx = y * img.rowstride
                for x in range(0, img.width):
                    assert rgbBufIdx == idx * 4
                    value = img.buf[bufIdx + x//2]
                    # (x & 0) always evaluates to 0. What are you trying to do?
                    # If you're trying to test the bit, you want to do "!(x & 1)".
                    # if x & 0:
                    if not (x & 1):
                        value >>= 4
                    cyan    = ((value >> 3) & 1) * 255
                    magenta = ((value >> 2) & 1) * 255
                    yellow  = ((value >> 1) & 1) * 255
                    black   = ( value       & 1) * 255
                    if not vall:
                        if not vc:
                            cyan = 0
                        if not vm:
                            magenta = 0
                        if  not vy:
                            yellow = 0
                        if not vk:
                            black = 0
                        if show_gray:
                            black += cyan + magenta + yellow
                            cyan = magenta = yellow = 0
                    
                    img.rgbbuf[rgbBufIdx] = (255-cyan)    * (255-black) // 255 # r
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = (255-magenta) * (255-black) // 255 # g
                    rgbBufIdx += 1
                    img.rgbbuf[rgbBufIdx] = (255-yellow)  * (255-black) // 255 # b
                    rgbBufIdx += 2
    elif color == gs.DISPLAY_COLORS_SEPARATION:
        if depth == gs.DISPLAY_DEPTH_8:
            num_comp = 0
            num_visible = 0
            show_gray = False
            
            for j in range(0, IMAGE_DEVICEN_MAX):
                if img.devicen[j].used:
                    num_comp = j+1
                    if img.devicen[j].visible:
                        num_visible += 1
            
            if num_visible == 1 and img.devicen_gray:
                show_gray = True
            
            rgbBufIdx = 0
            bufIdx = 0
            stride = img.rowstride - (img.width * 8)
            for idx in range(0, img.height * img.width):
                assert rgbBufIdx == idx * 4
                if idx % img.width is 0 and idx is not 0:
                    bufIdx += stride
                cyan = magenta = yellow = black = 0
                if show_gray:
                    for j in range(0, num_comp):
                        devicen = img.devicen[j]
                        if devicen.visible and devicen.used:
                            black += img.buf[bufIdx + j]
                else:
                    for j in range(0, num_comp):
                        devicen = img.devicen[j]
                        if devicen.visible and devicen.used:
                            value = img.buf[bufIdx + j]
                            cyan    += value * devicen.cyan    // 65535
                            magenta += value * devicen.magenta // 65535
                            yellow  += value * devicen.yellow  // 65535
                            black   += value * devicen.black   // 65535
                
                cyan    = min(255, cyan)
                magenta = min(255, magenta)
                yellow  = min(255, yellow)
                black   = min(255, black)
                
                img.rgbbuf[rgbBufIdx] = (255-yellow)    * (255-black) // 255 # r
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = (255-magenta) * (255-black) // 255 # g
                rgbBufIdx += 1
                img.rgbbuf[rgbBufIdx] = (255-cyan)  * (255-black) // 255 # b
                rgbBufIdx += 2
               
                bufIdx += 8
    
    if not isinstance(img.window, Gtk.Widget):
        window_create(img)
        window_resize(img)
    
    visible = img.window.get_visible()
    if not visible:
        img.window.show_all()
    
    img.darea.queue_draw()
    Gtk.main_iteration_do(False)
    return 0

def _display_page(handle, device, copies, flush):
    print '_display_page' #dbg
    _display_sync(handle, device)
    return 0;

def _display_update(handle, device, x, y, w, h):
    """ not implemented - eventually this will be used for progressive update """
    return 0

def _display_separation(handle, device, comp_num, name, c, m, y, k):
    print '_display_separation' , name, 'c', c, 'm', m, 'y', y, 'k', k, 'comp_num', comp_num #dbg
    img = image_find(handle, device)
    if img is None:
        return -1
    if comp_num < 0 or comp_num > IMAGE_DEVICEN_MAX:
        return -1
    
    img.devicen[comp_num].used = 1
    img.devicen[comp_num].name = name
    img.devicen[comp_num].cyan    = c
    img.devicen[comp_num].magenta = m
    img.devicen[comp_num].yellow  = y
    img.devicen[comp_num].black   = k
    return 0

# callback structure for "display" device
display_open       = gs.c_display_open(_display_open)
display_preclose   = gs.c_display_preclose(_display_preclose)
display_close      = gs.c_display_close(_display_close)
display_presize    = gs.c_display_presize(_display_presize)
display_size       = gs.c_display_size(_display_size)
display_sync       = gs.c_display_sync(_display_sync)
display_page       = gs.c_display_page(_display_page)
display_update     = gs.c_display_update(_display_update)
display_memalloc   = c.cast(None, gs.c_display_memalloc) # NULL,	/* memalloc */
display_memfree    = c.cast(None, gs.c_display_memfree) # NULL,	/* memfree */
display_separation = gs.c_display_separation(_display_separation)

display = gs.Display_callback_s(
    c.c_int(c.sizeof(gs.Display_callback_s)),
    c.c_int(gs.DISPLAY_VERSION_MAJOR),
    c.c_int(gs.DISPLAY_VERSION_MINOR),
    display_open,
    display_preclose,
    display_close,
    display_presize,
    display_size,
    display_sync,
    display_page,
    display_update,
    display_memalloc,
    display_memfree,
    display_separation
)

def main(argv):
    # int exit_status;
    # int code = 1, code1;
    # void *instance;
    # int nargc;
    # char **nargv;
    # char dformat[64];
    # int exit_code;
    # gboolean use_gui;
    
    code = 1
    use_gui, _ = Gtk.init_check(argv)
    
    # insert display device parameters as first arguments
    dformat = "-dDisplayFormat=%d" % \
            (gs.DISPLAY_COLORS_SEPARATION | gs.DISPLAY_ALPHA_NONE | gs.DISPLAY_DEPTH_8 | \
            gs.DISPLAY_BIGENDIAN | gs.DISPLAY_TOPFIRST)
    
    nargv = [argv[0], dformat] + argv[1:]
    
    #run Ghostscript 
    try:
        instance = gs.new_instance()
        gs.set_stdio(instance, gsdll_stdin, gsdll_stdout, gsdll_stderr)
        if use_gui:
            print('using gui: set_display_callback')
            gs.set_display_callback(instance, c.byref(display))
        print('init_with_args', instance, nargv)
        code = gs.init_with_args(instance, nargv)
        if code == 0:
            code = gs.run_string(instance, start_string)
        code1 = gs.exit(instance)
        if code == 0 or code == gs.e_Quit:
            code = code1
        if code == gs.e_Quit:
            code = 0 # user executed 'quit'
        gs.delete_instance(instance)
    except gs.GhostscriptError as e:
        code = e.code
        sys.stderr.write(e.message)
    finally:
        exit_status = 0;
        if code in [0, gs.e_Info, gs.e_Quit]:
            pass
        elif code == gs.e_Fatal:
            exit_status = 1
        else:
            exit_status = 255
    return exit_status

if __name__ == '__main__':
    main(sys.argv)
    #sys.exit(main(sys.argv))
