#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Ghostscript frontend which provides a graphical window
using PyGtk and python-ghostscript
"""
# 
# this is a python port from dxmain.c by artifex http://www.artifex.com
# dxmain.c is int the ghostscript repositoty at ghostpdl/gs/psi/dxmain.c
#
# Copyright 2013 by Lasse Fister <commander@graphicore.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#
#
# you will need to use python 2.x because cairo.ImageSurface.create_for_data
# is not yet available in python3:
# http://cairographics.org/documentation/pycairo/3/reference/surfaces.html#cairo.ImageSurface.create_for_data
#
# and this was not tested in python3
#
# Run this like the gs command is used. However, using the "display"
# device is required:
# $ ./dxmain.py -dBATCH -sDEVICE=display -dEPSFitPage /path/to/eps_or_pdf
# more options: http://www.ghostscript.com/doc/current/Use.htm#Output_device
#
# see the main function to change the setup of the display device


from __future__ import division

import ghostscript._gsprint as gs
import ctypes as c

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

# fails when being used:
# from gi.repository import cairo
# using regular bindings:
import cairo

import sys
from array import array



start_string = "systemdict /start get exec\n"

#####################################################################
# stdio functions

# this looks like not needed in python. a simple dict would do it
class Stdin_buf (c.Structure):
    _fields_ = [
        ('buf', c.POINTER(c.c_char)),
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
    if img and img.window and img.buf:
        bgcol = widget.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(bgcol.red, bgcol.blue, bgcol.green, bgcol.alpha)
        cr.paint()
        if img.rgbbuf:
            cairo_surface = cairo.ImageSurface.create_for_data(img.rgbbuf, cairo.FORMAT_RGB24, img.width, img.height, img.width * 4)
            cr.set_source_surface(cairo_surface, 0, 0)
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
    img.window = Gtk.Window(Gtk.WindowType.TOPLEVEL)
    img.window.set_title("python gs");
    
    img.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
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
    display_sync(img.handle, img.device)

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
    display_sync(img.handle, img.device)

def display_open(handle, device):
    """ New device has been opened """
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

def display_preclose(handle, device):
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

def display_close(handle, device):
    img = image_find(handle, device)
    if img is None:
        return -1
    # remove from list
    del images[(handle, device)]
    return 0;

def display_presize(handle, device, width, height, raster, format):
    # Assume everything is OK.
    # It would be better to return e_rangecheck if we can't
    # support the format.
    return 0;

def display_size(handle, device, width, height, raster, format, pimage):
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
    alpha = img.format & gs.DISPLAY_ALPHA_MASK
    
    if color == gs.DISPLAY_COLORS_CMYK:
        if depth == gs.DISPLAY_DEPTH_1 or depth == gs.DISPLAY_DEPTH_8:
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
    elif color == gs.DISPLAY_COLORS_NATIVE \
    and not (depth == gs.DISPLAY_DEPTH_8 or depth == gs.DISPLAY_DEPTH_16):
        return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_GRAY and depth != gs.DISPLAY_DEPTH_8:
        return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_RGB and depth != gs.DISPLAY_DEPTH_8:
        return gs.e_rangecheck # not supported
    elif color == gs.DISPLAY_COLORS_SEPARATION and depth != gs.DISPLAY_DEPTH_8:
        return gs.e_rangecheck # not supported
    
    if color == gs.DISPLAY_COLORS_CMYK or color == gs.DISPLAY_COLORS_SEPARATION:
        if not isinstance(img.cmyk_bar, Gtk.Widget):
            # add bar to select separation
            img.cmyk_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
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
    elif isinstance(img.cmyk_bar, Gtk.Widget):
        img.cmyk_bar.hide()
    window_resize(img)
    
    visible = img.window.get_visible()
    if not visible:
        img.window.show_all()

    Gtk.main_iteration_do(False)
    return 0

def display_sync(handle, device):
    """
    This will set a pixel buffer to img.rgbbuf in the the cairo.FORMAT_RGB24
    However the Format is documented as:
    "each pixel is a 32-bit quantity, with the upper 8 bits unused.
    Red, Green, and Blue are stored in the remaining 24 bits in that order."
    But on my local machine its BGRx not RGBx
    
    Real Alpha values where not tested just DISPLAY_ALPHA_NONE DISPLAY_UNUSED_FIRST and DISPLAY_UNUSED_LAST 
     
    This should be in C or something like that, as most of it would be a hundred times faster
    See the case for the native cairo.FORMAT_RGB24. Thats the only fast case.
    """
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
                    # RGB555
                    # worked with
                    # gs.DISPLAY_COLORS_NATIVE | gs.DISPLAY_DEPTH_16 | gs.DISPLAY_LITTLEENDIAN | gs.DISPLAY_NATIVE_555
                    img.rgbbuf = array('B')
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        if idx % img.width == 0 and idx != 0:
                            bufIdx += stride
                        w = img.buf[bufIdx] + (img.buf[bufIdx+1] << 8)
                        
                        value = w & 0x1f #blue
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 5) & 0x1f #green
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 10) & 0x1f #red
                        img.rgbbuf.append( (value << 3) + (value >> 2))
                        
                        img.rgbbuf.append(0) # x
                        
                        bufIdx += 2
                else:
                    # RGB565
                    # worked with
                    # gs.DISPLAY_COLORS_NATIVE | gs.DISPLAY_DEPTH_16 | gs.DISPLAY_LITTLEENDIAN | gs.DISPLAY_NATIVE_565
                    img.rgbbuf = array('B')
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        if idx % img.width == 0 and idx != 0:
                            bufIdx += stride
                        w = img.buf[bufIdx] + (img.buf[bufIdx+1] << 8)
                        
                        value = w & 0x1f # blue
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 5) & 0x3f # green
                        img.rgbbuf.append((value << 2) + (value >> 4))
                        
                        value = (w >> 11) & 0x1f #red
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        img.rgbbuf.append(0) # x
                        bufIdx += 2
            else:
                if native555 == gs.DISPLAY_NATIVE_555:
                    # RGB555
                    # worked with
                    # gs.DISPLAY_COLORS_NATIVE | gs.DISPLAY_DEPTH_16 | gs.DISPLAY_NATIVE_555 | gs.DISPLAY_BIGENDIAN
                    img.rgbbuf = array('B')
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        if idx % img.width == 0 and idx != 0:
                            bufIdx += stride
                        w = img.buf[bufIdx+1] + (img.buf[bufIdx] << 8)
                        
                        value = w & 0x1f # blue
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 5) & 0x1f # green
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 10) & 0x1f #red
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        img.rgbbuf.append(0) # x
                        bufIdx += 2
                else:
                    # RGB565
                    # worked with
                    # gs.DISPLAY_COLORS_NATIVE | gs.DISPLAY_DEPTH_16 | gs.DISPLAY_NATIVE_565 | gs.DISPLAY_BIGENDIAN
                    img.rgbbuf = array('B')
                    bufIdx = 0
                    stride = img.rowstride - (img.width * 2)
                    for idx in range(0, img.height * img.width):
                        if idx % img.width == 0 and idx != 0:
                            bufIdx += stride
                        w = img.buf[bufIdx+1] + (img.buf[bufIdx] << 8)
                        
                        value = w & 0x1f # blue
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        value = (w >> 5) & 0x3f # green
                        img.rgbbuf.append((value << 2) + (value >> 4))
                        
                        value = (w >> 11) & 0x1f # red
                        img.rgbbuf.append((value << 3) + (value >> 2))
                        
                        img.rgbbuf.append(0) # x
                        bufIdx += 2
        if depth == gs.DISPLAY_DEPTH_8:
            # palette of 96 colors
            # worked with
            # gs.DISPLAY_COLORS_NATIVE | gs.DISPLAY_DEPTH_8
            color = [[0,0,0]] * 96
            one = 255 // 3
            for i in range(0, 96):
                # 0->63 = 00RRGGBB, 64->95 = 010YYYYY
                if i < 64:
                    color[i] = (
                        ((i & 0x30) >> 4) * one, # r
                        ((i & 0x0c) >> 2) * one, # g
                         (i & 0x03)       * one  # b
                    )
                else:
                    value = i & 0x1f
                    value = (value << 3) + (value >> 2)
                    color[i] = (value, value, value)
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - img.width
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
                    bufIdx += stride
                w = img.buf[bufIdx]
                img.rgbbuf.extend([
                    color[w][2], # b
                    color[w][1], # g
                    color[w][0], # r
                    0            # x
                ])
                bufIdx += 1
    elif color == gs.DISPLAY_COLORS_GRAY:
        if depth == gs.DISPLAY_DEPTH_8:
            # gray 8 bit
            # worked with
            # gs.DISPLAY_COLORS_GRAY | gs.DISPLAY_DEPTH_8
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - img.width
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
                    bufIdx += stride
                w = img.buf[bufIdx]
                img.rgbbuf.extend([
                    w, # b
                    w, # g
                    w, # r
                    0  # x
                ])
                bufIdx += 1
    elif color == gs.DISPLAY_COLORS_RGB:
        if depth == gs.DISPLAY_DEPTH_8 and (
                alpha == gs.DISPLAY_ALPHA_FIRST or alpha == gs.DISPLAY_UNUSED_FIRST
            ) and endian == gs.DISPLAY_BIGENDIAN:
            # xRGB
            # worked with
            # gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_FIRST | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - (img.width * 4)
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
                    bufIdx += stride
                # img.buf[bufIdx] x = filler
                img.rgbbuf.extend([
                    img.buf[bufIdx + 3], # b
                    img.buf[bufIdx + 2], # g
                    img.buf[bufIdx + 1], # r
                    0                    # x
                ])
                bufIdx += 4
        elif depth == gs.DISPLAY_DEPTH_8 and endian == gs.DISPLAY_LITTLEENDIAN:
            if alpha == gs.DISPLAY_UNUSED_LAST or alpha == gs.DISPLAY_ALPHA_LAST:
                # cairo.FORMAT_RGB24 BGRx. no conversation is needed to display this with cairo
                # worked with
                # gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_LAST | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_LITTLEENDIAN
                bufIdx = 0
                hasStride = img.rowstride > img.width * 4
                if not hasStride:
                    # fast
                    buffer_size = img.height * img.width * 4
                    img.rgbbuf = c.create_string_buffer(buffer_size) 
                    c.memmove(img.rgbbuf, img.buf, buffer_size)
                else:
                    # slow. This has a stride between the rows, what is a bad thing
                    # thus we can't copy the buffer directly, like above
                    img.rgbbuf = array('B')
                    for y in range(0, img.height):
                        bufIdx = y * img.rowstride
                        img.rgbbuf.extend(img.buf[bufIdx:bufIdx+img.width * 4])
                    
            elif alpha == gs.DISPLAY_UNUSED_FIRST or alpha == gs.DISPLAY_ALPHA_FIRST:
                # xBGR
                # worked with
                # gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_FIRST | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_LITTLEENDIAN
                img.rgbbuf = array('B')
                bufIdx = 0
                stride = img.rowstride - (img.width * 4)
                for idx in range(0, img.height * img.width):
                    if idx % img.width == 0 and idx != 0:
                        bufIdx += stride
                    img.rgbbuf.extend([
                        img.buf[bufIdx + 1], # r
                        img.buf[bufIdx + 2], # g
                        img.buf[bufIdx + 3], # b
                        0                    # x
                    ])
                    bufIdx += 4
            else:
                # BGR24
                # worked with
                # gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_FIRST | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_ALPHA_NONE
                img.rgbbuf = array('B')
                bufIdx = 0
                stride = img.rowstride - (img.width * 3)
                for idx in range(0, img.height * img.width):
                    if idx % img.width == 0 and idx != 0:
                        bufIdx += stride
                    img.rgbbuf.extend([
                        img.buf[bufIdx    ], # b
                        img.buf[bufIdx + 1], # g
                        img.buf[bufIdx + 2], # r
                        0                    # x
                    ])
                    bufIdx += 3
        elif depth == gs.DISPLAY_DEPTH_8 and alpha == gs.DISPLAY_ALPHA_NONE \
            and endian == gs.DISPLAY_BIGENDIAN:
            # RGB24
            # worked with:
            # gs.DISPLAY_COLORS_RGB | gs.DISPLAY_ALPHA_NONE | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - (img.width * 3)
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
                    bufIdx += stride
                img.rgbbuf.extend([
                    img.buf[bufIdx + 2], # b
                    img.buf[bufIdx + 1], # g
                    img.buf[bufIdx + 0], # r
                    0                    # x
                ])
                bufIdx += 3
    elif color == gs.DISPLAY_COLORS_CMYK:
        if depth == gs.DISPLAY_DEPTH_8:
            # worked with:
            # gs.DISPLAY_COLORS_CMYK | gs.DISPLAY_ALPHA_NONE | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
            vc = img.devicen[0].visible
            vm = img.devicen[1].visible
            vy = img.devicen[2].visible
            vk = img.devicen[3].visible
            vall = vc and vm and vy and vk
            show_gray = (vc + vm + vy + vk == 1) and img.devicen_gray
            
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - (img.width * 4)
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
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
                
                img.rgbbuf.extend([
                    (255-yellow)  * (255-black) // 255, # b
                    (255-magenta) * (255-black) // 255, # g
                    (255-cyan)    * (255-black) // 255, # r
                    0                                   # x
                ])
                
                bufIdx += 4
        elif depth == gs.DISPLAY_DEPTH_1:
            # worked with:
            # gs.DISPLAY_COLORS_CMYK | gs.DISPLAY_ALPHA_NONE | gs.DISPLAY_DEPTH_1 | gs.DISPLAY_BIGENDIAN
            vc = img.devicen[0].visible
            vm = img.devicen[1].visible
            vy = img.devicen[2].visible
            vk = img.devicen[3].visible
            vall = vc and vm and vy and vk
            show_gray = (vc + vm + vy + vk == 1) and img.devicen_gray
            
            img.rgbbuf = array('B')
            for y in range(0, img.height):
                bufIdx = y * img.rowstride
                for x in range(0, img.width):
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
                    img.rgbbuf.extend([
                        (255-yellow)  * (255-black) // 255, # b
                        (255-magenta) * (255-black) // 255, # g
                        (255-cyan)    * (255-black) // 255, # r
                        0                                   # x
                    ])
    elif color == gs.DISPLAY_COLORS_SEPARATION:
        if depth == gs.DISPLAY_DEPTH_8:
            # worked with:
            # gs.DISPLAY_COLORS_SEPARATION | gs.DISPLAY_ALPHA_NONE | gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
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
            img.rgbbuf = array('B')
            bufIdx = 0
            stride = img.rowstride - (img.width * 8)
            for idx in range(0, img.height * img.width):
                if idx % img.width == 0 and idx != 0:
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
                img.rgbbuf.extend([
                    (255-yellow)  * (255-black) // 255, # b
                    (255-magenta) * (255-black) // 255, # g
                    (255-cyan)    * (255-black) // 255, # r
                    0                                   # x
                ])
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

def display_page(handle, device, copies, flush):
    display_sync(handle, device)
    return 0;

def display_update(handle, device, x, y, w, h):
    """ not implemented - eventually this will be used for progressive update """
    return 0

def display_separation(handle, device, comp_num, name, c, m, y, k):
    """ setup the colors for each used ink"""
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
display = gs.Display_callback_s(
    c.c_int(c.sizeof(gs.Display_callback_s)),
    c.c_int(gs.DISPLAY_VERSION_MAJOR),
    c.c_int(gs.DISPLAY_VERSION_MINOR),
    gs.c_display_open(display_open),
    gs.c_display_preclose(display_preclose),
    gs.c_display_close(display_close),
    gs.c_display_presize(display_presize),
    gs.c_display_size(display_size),
    gs.c_display_sync(display_sync),
    gs.c_display_page(display_page),
    #gs.c_display_update(display_update),
    c.cast(None, gs.c_display_update),
    c.cast(None, gs.c_display_memalloc), # NULL,	/* memalloc */
    c.cast(None, gs.c_display_memfree), # NULL,	/* memfree */
    gs.c_display_separation(display_separation)
)

def main(argv):
    code = 1
    use_gui, _ = Gtk.init_check(argv)
    
    # insert display device parameters as first arguments
    # this controls the format of the pixbuf that ghostscript will deliver
    # see display_sync for details
    
    # fast
    CAIRO_FORMAT_RGB24  = gs.DISPLAY_COLORS_RGB | gs.DISPLAY_UNUSED_LAST | \
                          gs.DISPLAY_DEPTH_8 | gs.DISPLAY_LITTLEENDIAN
    
    # interesting
    SEPARATION_FORMAT = gs.DISPLAY_COLORS_SEPARATION | gs.DISPLAY_ALPHA_NONE | \
                        gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
    
    # if there are spot colors they are mixed into the cmyk values
    CMYK_FORMAT = gs.DISPLAY_COLORS_CMYK | gs.DISPLAY_ALPHA_NONE | \
                  gs.DISPLAY_DEPTH_8 | gs.DISPLAY_BIGENDIAN
    
    dformat = "-dDisplayFormat=%d" % \
            ( CAIRO_FORMAT_RGB24 | gs.DISPLAY_TOPFIRST )
    
    nargv = [argv[0], dformat] + argv[1:]
    
    #run Ghostscript 
    try:
        instance = gs.new_instance()
        gs.set_stdio(instance, gsdll_stdin, gsdll_stdout, gsdll_stderr)
        if use_gui:
            gs.set_display_callback(instance, c.byref(display))
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
    code = main(sys.argv)
    sys.stdout.write('\n') # or bash will get out of sync ...
    sys.exit(code)
