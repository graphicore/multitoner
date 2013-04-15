# Ghostscript frontend which provides a graphical window
# using PyGtk.  Load time linking to libgs.so with python-ghostscript
# c-bindings
# 
# this is a python port from dxmain.c by artifex
# dxmain.c provides the "gs" command on linux shell
#

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <locale.h>
#include <gtk/Gtk.h>
#define __PROTOTYPES__
#include "ierrors.h"
#include "iapi.h"
#include "gdevdsp.h"

from __future__ import with_statement

import ghostscript._gsprint as gs
import ctypes as c

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

#ubuntu installed package: python-gi-cairo, not shure now if its needed
# fails when being used: from gi.repository import cairo
# using regular bindings:
# import cairo

import sys

start_string = "systemdict /start get exec\n"

static gboolean read_stdin_handler(GIOChannel *channel, GIOCondition condition,
        gpointer data);
static int gsdll_stdin(void *instance, char *buf, int len);
static int gsdll_stdout(void *instance, const char *str, int len);
static int gsdll_stdout(void *instance, const char *str, int len);
static int display_open(void *handle, void *device);
static int display_preclose(void *handle, void *device);
static int display_close(void *handle, void *device);
static int display_presize(void *handle, void *device, int width, int height,
        int raster, unsigned int format);
static int display_size(void *handle, void *device, int width, int height,
        int raster, unsigned int format, unsigned char *pimage);
static int display_sync(void *handle, void *device);
static int display_page(void *handle, void *device, int copies, int flush);
static int display_update(void *handle, void *device, int x, int y,
        int w, int h);

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
    else
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

_gsdll_stderr = gs.c_stdstream_call_t(_gsdll_stderr)


#####################################################################
# dll display device

class ImageDeviceN(object):
    """
        a dict would be sufficient here, but a class documents better
        what propertires are going to be used
    """
    used = None # int, non-zero if in use
    visible = None # int how on window
    name = None # char name[64]
    cyan = None # int
    magenta = None # int
    yellow = None # int
    black = None # int
    menu = None # int, non-zero if menu item added to system menu

IMAGE_DEVICEN_MAX 8

class Image(object):
    """
        a dict would be sufficient here, but a class documents better
        what propertires are going to be used
    """
    handle = None # void *handle
    device = None # void *device
    window = None # GtkWidget *window;
    vbox = None # GtkWidget *vbox;
    cmyk_bar = None # GtkWidget *cmyk_bar;
    separation = None # GtkWidget *separation[IMAGE_DEVICEN_MAX];
    show_as_gray = None # GtkWidget *show_as_gray;
    scroll = None # GtkWidget *scroll;
    darea = None # GtkWidget *darea;
    buf = None # guchar *buf;
    width = None # gint width;
    height = None # gint height;
    rowstride = None # gint rowstride;
    format = None # unsigned int format;
    devicen_gray = None # int devicen_gray; true if a single separation should be shown gray
    devicen = [] # IMAGE_DEVICEN devicen[IMAGE_DEVICEN_MAX];
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
        color = img.format & gs.DISPLAY_COLORS_MASK;
        depth = img.format & gs.DISPLAY_DEPTH_MASK;
        
        cr.set_source_color(widget.get_style_context()
            .get_background_color(Gtk.StateFlags.NORMAL))
        
        cr.paint()
        
        pixbuf = None
        # the declaration of pixbuf is mostly the same! dunno why it was made like this
        if color == gs.DISPLAY_COLORS_NATIVE:
            if depth == gs.DISPLAY_DEPTH_8 && img.rgbbuf:
                # https://developer.gnome.org/gdk-pixbuf/stable/gdk-pixbuf-Image-Data-in-Memory.html#gdk-pixbuf-new-from-data
                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                    GdkPixbuf.Colorspace.RGB, False, 8,
                    img.width, img.height, img.width*3,
                    None, None)
            elif depth == gs.DISPLAY_DEPTH_16 && img.rgbbuf:
                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                    GdkPixbuf.Colorspace.RGB, False, 8,
                    img.width, img.height, img.width*3,
                    None, None)
        elif color == gs.DISPLAY_COLORS_GRAY:
            if depth == gs.DISPLAY_DEPTH_8 && img.rgbbuf:
                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                    GdkPixbuf.Colorspace.RGB, False, 8,
                    img.width, img.height, img.width*3,
                    None, None)
            break;
        elif color == gs.DISPLAY_COLORS_RGB:
            if depth == gs.DISPLAY_DEPTH_8:
                if img.rgbbuf:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                        GdkPixbuf.Colorspace.RGB, False, 8,
                        img.width, img.height, img.width*3,
                        None, None)
                else:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.buf,
                        GdkPixbuf.Colorspace.RGB, False, 8,
                        img.width, img.height, img.rowstride,
                        None, None)
        elif color == gs.DISPLAY_COLORS_CMYK:
            if (depth == gs.DISPLAY_DEPTH_1 || depth == gs.DISPLAY_DEPTH_8) && img.rgbbuf:
                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                    GdkPixbuf.Colorspace.RGB, False, 8,
                    img.width, img.height, img.width*3,
                    None, None)
        elif color == gs.DISPLAY_COLORS_SEPARATION:
            if depth == gs.DISPLAY_DEPTH_8 && img.rgbbuf:
                pixbuf = GdkPixbuf.Pixbuf.new_from_data(img.rgbbuf,
                     GdkPixbuf.Colorspace.RGB, False, 8,
                    img.width, img.height, img.width*3,
                    None, None)
        if pixbuf:
            cr.set_source_pixbuf(pixbuf, 0, 0)
        cr.paint()
    return True

def window_destroy(widget, img):
    del img.window
    del img.scroll
    del img.darea

def window_create(img):
    """ Create a gtk window """
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
    img->scroll.add_with_viewport(img.darea)
    img.vbox.pack_start(img.scroll, true, true, 0)
    
    img.darea.connect('draw', window_draw, img)
    img.window.connect('destroy', window_destroy, img)
    img.window.connect('delete-event', Gtk.Widget.hide_on_delete, None)
    
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

static void window_separation(IMAGE *img, int sep)
{
    img->devicen[sep].visible = !img->devicen[sep].visible;
    display_sync(img->handle, img->device);
}

static void signal_sep0(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 0);
}

static void signal_sep1(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 1);
}

static void signal_sep2(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 2);
}

static void signal_sep3(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 3);
}

static void signal_sep4(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 4);
}

static void signal_sep5(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 5);
}

static void signal_sep6(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 6);
}

static void signal_sep7(GtkWidget *w, gpointer data)
{
    window_separation((IMAGE *)data, 7);
}

GCallback signal_separation[IMAGE_DEVICEN_MAX] = {
    (GCallback)signal_sep0,
    (GCallback)signal_sep1,
    (GCallback)signal_sep2,
    (GCallback)signal_sep3,
    (GCallback)signal_sep4,
    (GCallback)signal_sep5,
    (GCallback)signal_sep6,
    (GCallback)signal_sep7
};

static GtkWidget *
window_add_button(IMAGE *img, const char *label, GCallback fn)
{
    GtkWidget *w;
    w = gtk_check_button_new_with_label(label);
    gtk_box_pack_start(GTK_BOX(img->cmyk_bar), w, FALSE, FALSE, 5);
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w), TRUE);
    g_signal_connect(G_OBJECT(w), "clicked", fn, img);
    gtk_widget_show(w);
    return w;
}

static void signal_show_as_gray(GtkWidget *w, gpointer data)
{
    IMAGE *img= (IMAGE *)data;
    img->devicen_gray= !img->devicen_gray;
    display_sync(img->handle, img->device);
}

def _display_open(handle, device):
    """ New device has been opened """
    img = {}
    # add to list
    images[(handle, device)] = img
    # remember device and handle
    img['handle'] = handle
    img['device'] = device
    # create window
    window_create(img);
    Gtk.main_iteration_do(False)
    return 0;
}

static int display_preclose(void *handle, void *device)
{
    IMAGE *img = image_find(handle, device);
    if (img == NULL)
        return -1;

    gtk_main_iteration_do(FALSE);

    img->buf = NULL;
    img->width = 0;
    img->height = 0;
    img->rowstride = 0;
    img->format = 0;

    gtk_widget_destroy(img->window);
    img->window = NULL;
    img->scroll = NULL;
    img->darea = NULL;
    if (img->rgbbuf)
        free(img->rgbbuf);
    img->rgbbuf = NULL;

    gtk_main_iteration_do(FALSE);

    return 0;
}

static int display_close(void *handle, void *device)
{
    IMAGE *img = image_find(handle, device);
    if (img == NULL)
        return -1;

    /* remove from list */
    if (img == first_image) {
        first_image = img->next;
    }
    else {
        IMAGE *tmp;
        for (tmp = first_image; tmp!=0; tmp=tmp->next) {
            if (img == tmp->next)
                tmp->next = img->next;
        }
    }

    return 0;
}

static int display_presize(void *handle, void *device, int width, int height,
        int raster, unsigned int format)
{
    /* Assume everything is OK.
     * It would be better to return e_rangecheck if we can't
     * support the format.
     */
    return 0;
}

static int display_size(void *handle, void *device, int width, int height,
        int raster, unsigned int format, unsigned char *pimage)
{
    IMAGE *img = image_find(handle, device);
    int color;
    int depth;
    int i;
    gboolean visible;

    if (img == NULL)
        return -1;

    if (img->rgbbuf)
        free(img->rgbbuf);
    img->rgbbuf = NULL;

    img->width = width;
    img->height = height;
    img->rowstride = raster;
    img->buf = pimage;
    img->format = format;

    /* Reset separations */
    for (i=0; i<IMAGE_DEVICEN_MAX; i++) {
        img->devicen[i].used = 0;
        img->devicen[i].visible = 1;
        memset(img->devicen[i].name, 0, sizeof(img->devicen[i].name));
        img->devicen[i].cyan = 0;
        img->devicen[i].magenta = 0;
        img->devicen[i].yellow = 0;
        img->devicen[i].black = 0;
    }

    color = img->format & DISPLAY_COLORS_MASK;
    depth = img->format & DISPLAY_DEPTH_MASK;
    switch (color) {
        case DISPLAY_COLORS_NATIVE:
            if (depth == DISPLAY_DEPTH_8) {
                img->rgbbuf = (guchar *)malloc(width * height * 3);
                if (img->rgbbuf == NULL)
                    return -1;
                break;
            }
            else if (depth == DISPLAY_DEPTH_16) {
                /* need to convert to 24RGB */
                img->rgbbuf = (guchar *)malloc(width * height * 3);
                if (img->rgbbuf == NULL)
                    return -1;
            }
            else
                return e_rangecheck;	/* not supported */
        case DISPLAY_COLORS_GRAY:
            if (depth == DISPLAY_DEPTH_8) {
                img->rgbbuf = (guchar *)malloc(width * height * 3);
                if (img->rgbbuf == NULL)
                    return -1;
                break;
            }
            else
                return -1;	/* not supported */
        case DISPLAY_COLORS_RGB:
            if (depth == DISPLAY_DEPTH_8) {
                if (((img->format & DISPLAY_ALPHA_MASK) == DISPLAY_ALPHA_NONE)
                    && ((img->format & DISPLAY_ENDIAN_MASK)
                        == DISPLAY_BIGENDIAN))
                    break;
                else {
                    /* need to convert to 24RGB */
                    img->rgbbuf = (guchar *)malloc(width * height * 3);
                    if (img->rgbbuf == NULL)
                        return -1;
                }
            }
            else
                return -1;	/* not supported */
            break;
        case DISPLAY_COLORS_CMYK:
            if ((depth == DISPLAY_DEPTH_1) || (depth == DISPLAY_DEPTH_8)) {
                /* need to convert to 24RGB */
                img->rgbbuf = (guchar *)malloc(width * height * 3);
                if (img->rgbbuf == NULL)
                    return -1;
                /* We already know about the CMYK components */
                img->devicen[0].used = 1;
                img->devicen[0].cyan = 65535;
                strncpy(img->devicen[0].name, "Cyan",
                    sizeof(img->devicen[0].name));
                img->devicen[1].used = 1;
                img->devicen[1].magenta = 65535;
                strncpy(img->devicen[1].name, "Magenta",
                    sizeof(img->devicen[1].name));
                img->devicen[2].used = 1;
                img->devicen[2].yellow = 65535;
                strncpy(img->devicen[2].name, "Yellow",
                    sizeof(img->devicen[2].name));
                img->devicen[3].used = 1;
                img->devicen[3].black = 65535;
                strncpy(img->devicen[3].name, "Black",
                    sizeof(img->devicen[3].name));
            }
            else
                return -1;	/* not supported */
            break;
        case DISPLAY_COLORS_SEPARATION:
            /* we can't display this natively */
            /* we will convert it just before displaying */
            if (depth != DISPLAY_DEPTH_8)
                return -1;	/* not supported */
            img->rgbbuf = (guchar *)malloc(width * height * 3);
            if (img->rgbbuf == NULL)
                return -1;
            break;
    }

    if ((color == DISPLAY_COLORS_CMYK) ||
        (color == DISPLAY_COLORS_SEPARATION)) {
        if (!GTK_IS_WIDGET(img->cmyk_bar)) {
            /* add bar to select separation */
#if !GTK_CHECK_VERSION(3, 0, 0)
            img->cmyk_bar = gtk_hbox_new(FALSE, 0);
#else
            img->cmyk_bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
            gtk_box_set_homogeneous(img->cmyk_bar, FALSE);
#endif
            gtk_box_pack_start(GTK_BOX(img->vbox), img->cmyk_bar,
                FALSE, FALSE, 0);
            for (i=0; i<IMAGE_DEVICEN_MAX; i++) {
               img->separation[i] =
                window_add_button(img, img->devicen[i].name,
                   signal_separation[i]);
            }
            img->show_as_gray = gtk_check_button_new_with_label("Show as Gray");
            gtk_box_pack_end(GTK_BOX(img->cmyk_bar), img->show_as_gray,
                FALSE, FALSE, 5);
            gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(img->show_as_gray),
                FALSE);
            g_signal_connect(G_OBJECT(img->show_as_gray), "clicked",
                G_CALLBACK(signal_show_as_gray), img);
            gtk_widget_show(img->show_as_gray);
        }
        gtk_widget_show(img->cmyk_bar);
    }
    else {
        if (GTK_IS_WIDGET(img->cmyk_bar))
            gtk_widget_hide(img->cmyk_bar);
    }

    window_resize(img);

#if !GTK_CHECK_VERSION(3, 0, 0)
    visible = (GTK_WIDGET_FLAGS(img->window) & GTK_VISIBLE);
#else
    visible = gtk_widget_get_visible(img->window);
#endif

    if (!visible) gtk_widget_show_all(img->window);

    gtk_main_iteration_do(FALSE);
    return 0;
}

static int display_sync(void *handle, void *device)
{
    IMAGE *img = image_find(handle, device);
    int color;
    int depth;
    int endian;
    int native555;
    int alpha;
    gboolean visible;

    if (img == NULL)
        return -1;

    color = img->format & DISPLAY_COLORS_MASK;
    depth = img->format & DISPLAY_DEPTH_MASK;
    endian = img->format & DISPLAY_ENDIAN_MASK;
    native555 = img->format & DISPLAY_555_MASK;
    alpha = img->format & DISPLAY_ALPHA_MASK;

    if ((color == DISPLAY_COLORS_CMYK) ||
        (color == DISPLAY_COLORS_SEPARATION)) {
        /* check if separations have changed */
        int i;
        const gchar *str;
        for (i=0; i<IMAGE_DEVICEN_MAX; i++) {
            str = gtk_label_get_text(
                GTK_LABEL(gtk_bin_get_child(GTK_BIN(img->separation[i]))));
            if (!img->devicen[i].used)
                gtk_widget_hide(img->separation[i]);
            else if (strcmp(img->devicen[i].name, str) != 0) {
                /* text has changed, update it */
                gtk_label_set_text(
                    GTK_LABEL(gtk_bin_get_child(GTK_BIN(img->separation[i]))),
                    img->devicen[i].name);
                gtk_widget_show(img->separation[i]);
            }
        }
    }

    /* some formats need to be converted for use by GdkRgb */
    switch (color) {
        case DISPLAY_COLORS_NATIVE:
            if (depth == DISPLAY_DEPTH_16) {
              if (endian == DISPLAY_LITTLEENDIAN) {
                if (native555 == DISPLAY_NATIVE_555) {
                    /* BGR555 */
                    int x, y;
                    unsigned short w;
                    unsigned char value;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            w = s[0] + (s[1] << 8);
                            value = (w >> 10) & 0x1f;	/* red */
                            *d++ = (value << 3) + (value >> 2);
                            value = (w >> 5) & 0x1f;	/* green */
                            *d++ = (value << 3) + (value >> 2);
                            value = w & 0x1f;		/* blue */
                            *d++ = (value << 3) + (value >> 2);
                            s += 2;
                        }
                    }
                }
                else {
                    /* BGR565 */
                    int x, y;
                    unsigned short w;
                    unsigned char value;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            w = s[0] + (s[1] << 8);
                            value = (w >> 11) & 0x1f;	/* red */
                            *d++ = (value << 3) + (value >> 2);
                            value = (w >> 5) & 0x3f;	/* green */
                            *d++ = (value << 2) + (value >> 4);
                            value = w & 0x1f;		/* blue */
                            *d++ = (value << 3) + (value >> 2);
                            s += 2;
                        }
                    }
                }
              }
              else {
                if (native555 == DISPLAY_NATIVE_555) {
                    /* RGB555 */
                    int x, y;
                    unsigned short w;
                    unsigned char value;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            w = s[1] + (s[0] << 8);
                            value = (w >> 10) & 0x1f;	/* red */
                            *d++ = (value << 3) + (value >> 2);
                            value = (w >> 5) & 0x1f;	/* green */
                            *d++ = (value << 3) + (value >> 2);
                            value = w & 0x1f;		/* blue */
                            *d++ = (value << 3) + (value >> 2);
                            s += 2;
                        }
                    }
                }
                else {
                    /* RGB565 */
                    int x, y;
                    unsigned short w;
                    unsigned char value;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            w = s[1] + (s[0] << 8);
                            value = (w >> 11) & 0x1f;	/* red */
                            *d++ = (value << 3) + (value >> 2);
                            value = (w >> 5) & 0x3f;	/* green */
                            *d++ = (value << 2) + (value >> 4);
                            value = w & 0x1f;		/* blue */
                            *d++ = (value << 3) + (value >> 2);
                            s += 2;
                        }
                    }
                }
              }
            }
            if (depth == DISPLAY_DEPTH_8) {
                /* palette of 96 colors */
                guchar color[96][3];
                int i;
                int one = 255 / 3;
                int x, y;
                unsigned char *s, *d;

                for (i=0; i<96; i++) {
                    /* 0->63 = 00RRGGBB, 64->95 = 010YYYYY */
                    if (i < 64) {
                        color[i][0] =
                            ((i & 0x30) >> 4) * one; /* r */
                        color[i][1] =
                            ((i & 0x0c) >> 2) * one; /* g */
                        color[i][2] =
                            (i & 0x03) * one; /* b */
                    }
                    else {
                        int val = i & 0x1f;
                        val = (val << 3) + (val >> 2);
                        color[i][0] = color[i][1] = color[i][2] = val;
                    }
                }

                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                            *d++ = color[*s][0];	/* r */
                            *d++ = color[*s][1];	/* g */
                            *d++ = color[*s][2];	/* b */
                            s++;
                    }
                }
            }
            break;
        case DISPLAY_COLORS_GRAY:
            if (depth == DISPLAY_DEPTH_8) {
                int x, y;
                unsigned char *s, *d;
                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                            *d++ = *s;	/* r */
                            *d++ = *s;	/* g */
                            *d++ = *s;	/* b */
                            s++;
                    }
                }
            }
            break;
        case DISPLAY_COLORS_RGB:
            if ( (depth == DISPLAY_DEPTH_8) &&
                 ((alpha == DISPLAY_ALPHA_FIRST) ||
                  (alpha == DISPLAY_UNUSED_FIRST)) &&
                 (endian == DISPLAY_BIGENDIAN) ) {
                /* Mac format */
                int x, y;
                unsigned char *s, *d;
                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                        s++;		/* x = filler */
                        *d++ = *s++;	/* r */
                        *d++ = *s++;	/* g */
                        *d++ = *s++;	/* b */
                    }
                }
            }
            else if ( (depth == DISPLAY_DEPTH_8) &&
                      (endian == DISPLAY_LITTLEENDIAN) ) {
                if ((alpha == DISPLAY_UNUSED_LAST) ||
                    (alpha == DISPLAY_ALPHA_LAST)) {
                    /* Windows format + alpha = BGRx */
                    int x, y;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            *d++ = s[2];	/* r */
                            *d++ = s[1];	/* g */
                            *d++ = s[0];	/* b */
                            s += 4;
                        }
                    }
                }
                else if ((alpha == DISPLAY_UNUSED_FIRST) ||
                    (alpha == DISPLAY_ALPHA_FIRST)) {
                    /* xBGR */
                    int x, y;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            *d++ = s[3];	/* r */
                            *d++ = s[2];	/* g */
                            *d++ = s[1];	/* b */
                            s += 4;
                        }
                    }
                }
                else {
                    /* Windows BGR24 */
                    int x, y;
                    unsigned char *s, *d;
                    for (y = 0; y<img->height; y++) {
                        s = img->buf + y * img->rowstride;
                        d = img->rgbbuf + y * img->width * 3;
                        for (x=0; x<img->width; x++) {
                            *d++ = s[2];	/* r */
                            *d++ = s[1];	/* g */
                            *d++ = s[0];	/* b */
                            s += 3;
                        }
                    }
                }
            }
            break;
        case DISPLAY_COLORS_CMYK:
            if (depth == DISPLAY_DEPTH_8) {
                /* Separations */
                int x, y;
                int cyan, magenta, yellow, black;
                unsigned char *s, *d;
                int vc = img->devicen[0].visible;
                int vm = img->devicen[1].visible;
                int vy = img->devicen[2].visible;
                int vk = img->devicen[3].visible;
                int vall = vc && vm && vy && vk;
                int show_gray = (vc + vm + vy + vk == 1) && img->devicen_gray;
                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                        cyan = *s++;
                        magenta = *s++;
                        yellow = *s++;
                        black = *s++;
                        if (!vall) {
                            if (!vc)
                                cyan = 0;
                            if (!vm)
                                magenta = 0;
                            if (!vy)
                                yellow = 0;
                            if (!vk)
                                black = 0;
                            if (show_gray) {
                                black += cyan + magenta + yellow;
                                cyan = magenta = yellow = 0;
                            }
                        }
                        *d++ = (255-cyan)    * (255-black) / 255; /* r */
                        *d++ = (255-magenta) * (255-black) / 255; /* g */
                        *d++ = (255-yellow)  * (255-black) / 255; /* b */
                    }
                }
            }
            else if (depth == DISPLAY_DEPTH_1) {
                /* Separations */
                int x, y;
                int cyan, magenta, yellow, black;
                unsigned char *s, *d;
                int vc = img->devicen[0].visible;
                int vm = img->devicen[1].visible;
                int vy = img->devicen[2].visible;
                int vk = img->devicen[3].visible;
                int vall = vc && vm && vy && vk;
                int show_gray = (vc + vm + vy + vk == 1) && img->devicen_gray;
                int value;
                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                        value = s[x/2];
                        if (x & 0)
                            value >>= 4;
                        cyan = ((value >> 3) & 1) * 255;
                        magenta = ((value >> 2) & 1) * 255;
                        yellow = ((value >> 1) & 1) * 255;
                        black = (value & 1) * 255;
                        if (!vall) {
                            if (!vc)
                                cyan = 0;
                            if (!vm)
                                magenta = 0;
                            if (!vy)
                                yellow = 0;
                            if (!vk)
                                black = 0;
                            if (show_gray) {
                                black += cyan + magenta + yellow;
                                cyan = magenta = yellow = 0;
                            }
                        }
                        *d++ = (255-cyan)    * (255-black) / 255; /* r */
                        *d++ = (255-magenta) * (255-black) / 255; /* g */
                        *d++ = (255-yellow)  * (255-black) / 255; /* b */
                    }
                }
            }
            break;
        case DISPLAY_COLORS_SEPARATION:
            if (depth == DISPLAY_DEPTH_8) {
                int j;
                int x, y;
                unsigned char *s, *d;
                int cyan, magenta, yellow, black;
                int num_comp = 0;
                int value;
                int num_visible = 0;
                int show_gray = 0;
                IMAGE_DEVICEN *devicen = img->devicen;
                for (j=0; j<IMAGE_DEVICEN_MAX; j++) {
                    if (img->devicen[j].used) {
                       num_comp = j+1;
                       if (img->devicen[j].visible)
                            num_visible++;
                    }
                }
                if ((num_visible == 1) && img->devicen_gray)
                    show_gray = 1;

                for (y = 0; y<img->height; y++) {
                    s = img->buf + y * img->rowstride;
                    d = img->rgbbuf + y * img->width * 3;
                    for (x=0; x<img->width; x++) {
                        cyan = magenta = yellow = black = 0;
                        if (show_gray) {
                            for (j=0; j<num_comp; j++) {
                                devicen = &img->devicen[j];
                                if (devicen->visible && devicen->used)
                                    black += s[j];
                            }
                        }
                        else {
                            for (j=0; j<num_comp; j++) {
                                devicen = &img->devicen[j];
                                if (devicen->visible && devicen->used) {
                                    value = s[j];
                                    cyan    += value*devicen->cyan   /65535;
                                    magenta += value*devicen->magenta/65535;
                                    yellow  += value*devicen->yellow /65535;
                                    black   += value*devicen->black  /65535;
                                }
                            }
                        }
                        if (cyan > 255)
                           cyan = 255;
                        if (magenta > 255)
                           magenta = 255;
                        if (yellow > 255)
                           yellow = 255;
                        if (black > 255)
                           black = 255;
                        *d++ = (255-cyan)    * (255-black) / 255; /* r */
                        *d++ = (255-magenta) * (255-black) / 255; /* g */
                        *d++ = (255-yellow)  * (255-black) / 255; /* b */
                        s += 8;
                    }
                }
            }
            break;
    }

    if (!GTK_IS_WIDGET(img->window)) {
        window_create(img);
        window_resize(img);
    }
#if !GTK_CHECK_VERSION(3, 0, 0)
    visible = (GTK_WIDGET_FLAGS(img->window) & GTK_VISIBLE);
#else
    visible = gtk_widget_get_visible(img->window);
#endif

    if (!visible) gtk_widget_show_all(img->window);

    gtk_widget_queue_draw(img->darea);
    gtk_main_iteration_do(FALSE);
    return 0;
}

static int display_page(void *handle, void *device, int copies, int flush)
{
    display_sync(handle, device);
    return 0;
}

static int display_update(void *handle, void *device,
    int x, int y, int w, int h)
{
    /* not implemented - eventually this will be used for progressive update */
    return 0;
}

static int
display_separation(void *handle, void *device,
    int comp_num, const char *name,
    unsigned short c, unsigned short m,
    unsigned short y, unsigned short k)
{
    IMAGE *img = image_find(handle, device);
    if (img == NULL)
        return -1;
    if ((comp_num < 0) || (comp_num > IMAGE_DEVICEN_MAX))
        return -1;
    img->devicen[comp_num].used = 1;
    strncpy(img->devicen[comp_num].name, name,
        sizeof(img->devicen[comp_num].name)-1);
    img->devicen[comp_num].cyan    = c;
    img->devicen[comp_num].magenta = m;
    img->devicen[comp_num].yellow  = y;
    img->devicen[comp_num].black   = k;
    return 0;
}

# callback structure for "display" device
display_open       = gs.c_display_open(_display_open)
display_preclose   = gs.c_display_preclose(_display_preclose)
display_close      = gs.c_display_close(_display_close)
display_presize    = gs.c_display_presize(_display_presize)
display_size       = gs.c_display_size(_display_size)
display_sync       = gs.c_display_sync(_display_sync)
display_page       = gs.c_display_page(_display_page)
display_update     = gs.c_display_update(_display_update)
display_memalloc   = cast(None, gs.c_display_memalloc) # NULL,	/* memalloc */
display_memfree    = cast(None, gs.c_display_memfree) # NULL,	/* memfree */
display_separation = gs.c_display_separation(_display_separation)

display_callback = gs.Display_callback_s(
    c_int(sizeof(Display_callback_s)),
    c_int(gs.DISPLAY_VERSION_MAJOR),
    c_int(gs.DISPLAY_VERSION_MINOR),
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
    
    # use_gui = Gtk.init_check()
    # ??? used to be (in c)  use_gui = gtk_init_check(&argc, &argv);
    # but it takes no args in pygtk ... 
    # https://developer.gnome.org/pygtk/stable/gtk-functions.html#function-gtk--init-check
    use_gui = True
    
    # insert display device parameters as first arguments
    dformat = "-dDisplayFormat=%d" % \
            DISPLAY_COLORS_RGB | DISPLAY_ALPHA_NONE | DISPLAY_DEPTH_8 | \
            DISPLAY_BIGENDIAN | DISPLAY_TOPFIRST
    
    nargv = [argv[0], dformat] + argv[1:]
    
    #run Ghostscript 
    try
        instance = gs.new_instance()
        gs.set_stdio(instance, gsdll_stdin, gsdll_stdout, gsdll_stderr)
        if (use_gui)
            gs.set_display_callback(instance, display)
        code = gs.init_with_args(instance, nargv)
        if code == 0:
            code = gs.run_string(instance, start_string)
        code1 = gs_exit(instance)
        if code == 0 or code == gs.e_Quit:
            code = code1
        if code == gs.e_Quit:
            code = 0 # user executed 'quit'
        gs.delete_instance(instance)
    except GhostscriptError as e:
        code = e.code
        sys.stderr.write(e)
        pass
    finally:
        exit_status = 0;
        if code in [0, gs.e_Info, gs.e_Quit]:
            pass
        elif code == gs.e_Fatal
            exit_status = 1
        else
            exit_status = 255
        return exit_status

if __name__ == '__main__':
     sys.exit(main(sys.argv))
