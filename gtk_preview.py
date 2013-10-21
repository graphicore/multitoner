#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2013 by Lasse Fister <commander@graphicore.de>
# 
# This file is part of Multitoner.
#
# Multitoner is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Multitoner is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division, print_function, unicode_literals

import os

from gi.repository import Gtk, GObject, Gdk, GLib, GdkPixbuf
from gtk_actiongroup import ActionGroup
import cairo
from weakref import ref as weakref
import math
from compatibility import repair_gsignals, decode
from gtk_dialogs import show_open_image_dialog, show_message, show_save_as_eps_dialog
from mtt2eps import model2eps

__all__ = ['PreviewWindow']

DIRECTORY = decode(os.path.dirname(os.path.realpath(__file__)))

# just a preparation for i18n
def _(string):
    return string

UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action="FileMenu">
      <menuitem action='OpenImage' />
      <separator />
      <menuitem action='ExportImage' />
      <separator />
      <menuitem action='Quit' />
    </menu>
    <menu action="EditMenu">
      <menuitem action='ZoomIn' />
      <menuitem action='ZoomOut' />
      <menuitem action='ZoomUnit' />
      <menuitem action='ZoomFit' />
      <separator />
      <menuitem action='RotateRight' />
      <menuitem action='RotateLeft' />
    </menu>
  </menubar>
  <toolbar name="ToolBar">
      <toolitem action='OpenImage' />
      <separator />
      <toolitem action='ExportImage' />
      <separator />
      <toolitem action='ZoomIn' />
      <toolitem action='ZoomOut' />
      <toolitem action='ZoomUnit' />
      <toolitem action='ZoomFit' />
      <separator />
      <toolitem action='RotateRight' />
      <toolitem action='RotateLeft' />
      <separator />
      <toolitem action='Quit' />
  </toolbar>
</ui>
"""

class Canvas(Gtk.Viewport):
    """ Handle the display and transformation of a cairo_surface """
    
    __gsignals__ = repair_gsignals({
        'scale-to-fit-changed': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                                 # the value of scale_to_fit
                                 GObject.TYPE_BOOLEAN, ))
    })
    
    def __init__(self, *args):
        Gtk.Viewport.__init__(self, *args)
        
        self._transformed_pattern_cache = (None, None)
        
        self._source_surface = None
        
        self._center = None
        self._restoring_center = False
        self._timers = {}
        
        self.da = Gtk.DrawingArea()
        self.add(self.da)
        self._init_event_handlers()
    
    def _init_event_handlers(self):
        self.da.connect('draw' , self.draw_handler)
        self.da.add_events(
            Gdk.EventMask.STRUCTURE_MASK # needed for configure-event
        )
        self.da.connect('configure-event', self.configure_handler)
        self.get_vadjustment().connect(
            'value-changed', self.adjustment_value_changed_handler)
        self.get_hadjustment().connect(
            'value-changed', self.adjustment_value_changed_handler)
        
        # this will keep the center of the image in the center of the window
        # when the window is beeing resized
        self.add_events(
            Gdk.EventMask.STRUCTURE_MASK # needed for configure-event
        )
        def realize_handler(widget, *args):
            """ 
            closure to connect to window when it establishes this widget
            """
            window = widget.get_toplevel()
            window.connect('configure-event', self.toplevel_configure_handler)
            
            parent = widget.get_parent()
            parent.connect('size-allocate', self.parent_size_allocate_handler)
            
            widget.disconnect(realize_handler_id)
        # save realize_handler_id for the closure of onRealize 
        realize_handler_id = self.connect('realize' , realize_handler)
    
    def _get_bbox(self, matrix, x1, y1, x2, y2):
        """
        transform the rectangle defined by x1, y1, x2, y2 and return
        the bounding box of the result rectangle
        """
        in_points = ( (x1, y1)
                    , (x1, y2)
                    , (x2, y1)
                    , (x2, y2)
                    )
        out_points = [matrix.transform_point(x, y) for x, y in in_points]
        
        xs, ys = zip(*out_points)
        
        max_x = max(*xs)
        max_y = max(*ys)
        
        min_x = min(*xs)
        min_y = min(*ys)
        
        return min_x, min_y, max_x, max_y
    
    def _get_bbox_extents(self, matrix, x1, y1, x2, y2):
        """
        apply matrix to the rectangle defined by x1, y1, x2, y2
        returns width, height, offset_x, offset_y of the bounding box
        this is used to determine the space needed to draw the surface
        and to move the contents back into view using the offsets
        """
        x1, y1, x2, y2 = self._get_bbox(matrix, x1, y1, x2, y2)
        w = int(math.ceil(x2-x1))
        h = int(math.ceil(y2-y1))
        offset_x, offset_y = x1, y1
        return w, h, offset_x, offset_y
    
    def _get_surface_extents(self, matrix, surface):
        """
        get the extents and offsets of surface after the application
        of matrix
        """
        x1, y1, x2, y2 = 0, 0, surface.get_width(), surface.get_height()
        return self._get_bbox_extents(matrix, x1, y1, x2, y2)
    
    def _get_rotated_matrix(self):
        """ matrix with rotation but without scale"""
        matrix = cairo.Matrix()
        matrix.rotate(self.rotation * math.pi)
        # rotate?
        return matrix

    def _save_center(self):
        if self._restoring_center == True:
            return
        center = (
        #   (scrollbar position                 + screen width                 / 2)) / image width
            (self.get_hadjustment().get_value() + (self.get_allocated_width()  / 2)) / self.da.get_allocated_width()
        #   (scrollbar position                 + screen height                / 2)) / image height
          , (self.get_vadjustment().get_value() + (self.get_allocated_height() / 2)) / self.da.get_allocated_height()
        )
        self._center = center
        return center
    
    def _get_scaled_matrix(self):
        """ matrix with rotation and scale"""
        matrix = self._get_rotated_matrix()
        matrix.scale(self.scale, self.scale)
        return matrix
    
    def _resize(self):
        # needs bounding box width and height after all transformations
        if self._source_surface is not None:
            matrix = self._get_scaled_matrix()
            w, h, _, _ = self._get_surface_extents(matrix, self._source_surface)
        else:
            w = h = 0
        self.da.set_size_request(w, h)
    
    def _set_scale(self, value):
        """ will set the new scale"""
        if self.scale == value:
            return
        self._scale = value
        self._save_center()
        self._resize()
        self.da.queue_draw()
    
    def _set_fitting_scale(self, available_width, available_height):
        """
        set the scale to a value that makes the image fit exactly into
        available_width and available_height
        """
        if self._source_surface is None:
            return
        # needs unscaled width and unscaled height, so the matrix must not
        # be scaled, the rotation however is needed
        matrix = self._get_rotated_matrix()
        source_width, source_height, _, _ = self._get_surface_extents(matrix, self._source_surface)
        try:
            aspect_ratio = source_width / source_height
            available_aspect_ratio = available_width / available_height
        except ZeroDivisionError:
            self._set_scale(1)
        else:
            if aspect_ratio > available_aspect_ratio:
                # fit to width
                self._set_scale(available_width / source_width)
            else: 
                # fit to height
                self._set_scale(available_height / source_height)
    
    def set_fitting_scale(self):
        parent = self.get_parent()
        if parent is None:
            return
        parent_allocation = parent.get_allocation()
        self._set_fitting_scale(parent_allocation.width, parent_allocation.height)
    
    def receive_surface(self, surface):
        self._source_surface = surface
        if not hasattr(self, '_scale') or self.scale_to_fit:
            self.set_fitting_scale()
        else:
            self._resize()
        self.da.queue_draw()

    def _restore_center(self):
        if self._center is None:
            return
        self._restoring_center = True
        try:
            h, v = self._center
            #      image width                    * center of view - screen width   / 2
            left = self.da.get_allocated_width()  * h - self.get_allocated_width()  / 2
            #      image height                   * center of view - screen height  / 2
            top  = self.da.get_allocated_height() * v - self.get_allocated_height() / 2
            self.get_hadjustment().set_value(left)
            self.get_vadjustment().set_value(top)
        finally:
            self._restoring_center = False

    def configure_handler(self, widget, event):
        """
        the configure event signals when the DrawingArea got resized
        happens after receive_surface and can be handled immediately
        """
        if not self.scale_to_fit:
            self._restore_center()
    
    """ when the toplevel window got resized """
    toplevel_configure_handler = configure_handler
    
    def parent_size_allocate_handler(self, parent, allocation):
        if self.scale_to_fit:
            self._set_fitting_scale(allocation.width, allocation.height)
    
    def adjustment_value_changed_handler(self, adjustment):
        self._save_center()
    
    @property
    def rotation(self):
        return getattr(self, '_rotation', 0)
    
    @rotation.setter
    def rotation(self, value):
        """ between 0 and 2 will be multiplied with PI => radians """
        self._rotation = value % 2
        if self.scale_to_fit:
            self.set_fitting_scale()
        self._resize()
        self.da.queue_draw()
    
    def add_rotation(self, value):
        self.rotation += value
    
    @property
    def scale(self):
        return getattr(self, '_scale', 1.0)
    
    @scale.setter
    def scale(self, value):
        """ will turn off scale to fit and set the new scale"""
        self.scale_to_fit = False
        self._set_scale(value)
    
    @property
    def scale_to_fit(self):
        return getattr(self, '_scale_to_fit', True)
    
    @scale_to_fit.setter
    def scale_to_fit(self, value):
        old = self.scale_to_fit
        self._scale_to_fit = not not value
        if self._scale_to_fit != old:
            self.emit('scale-to-fit-changed', self._scale_to_fit)
        if self._scale_to_fit:
            self.set_fitting_scale()
    
    def _create_transformed_pattern(self, source_surface, transform_buffer=True):
        """
        returns cairo pattern to set as source of a cairo context
        
        When transform_buffer is False the returned pattern will have all
        necessary transformations applied to its affine transformation
        matrix. The source buffer, however will be the original source_surface.
        So drawing that pattern will apply all transformations life, this
        can result in a lot of cpu work when the pattern is drawn multiple
        times.
        
        When transform_buffer is True, the returned pattern will be a
        pattern with no extra transformations applied. Instead its surface
        will hold the image data after all transformations have been applied.
        """
        # calculate width and height using the new matrix
        matrix = self._get_scaled_matrix()
        w, h, offset_x, offset_y = self._get_surface_extents(matrix, source_surface)
        
        # finish the transformation matrix by translating the pattern
        # back into view using the offsets the transformation created.
        # IMPORTANT: the normal translate method of a cairo.Matrix applies
        # before all other transformations. Here we need it to be applied
        # after all transformations, hence the usage of multiply
        translate_matrix = cairo.Matrix()
        translate_matrix.translate(-offset_x, -offset_y)
        matrix = matrix.multiply(translate_matrix)
        
        source_pattern = cairo.SurfacePattern(source_surface)
        # cairo.SurfacePattern uses inverted matrices, see the docs for pattern
        matrix.invert()
        source_pattern.set_matrix(matrix)
        if not transform_buffer:
            return source_pattern
        # the result of this can be cached and will speedup the display
        # for large images alot, because all transformations will be applied
        # just once not on every draw signal
        target_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        # the context to draw on the new surface
        co = cairo.Context(target_surface)
        # draw to target_surface
        co.set_source(source_pattern)
        co.paint()
        target_pattern = cairo.SurfacePattern(target_surface)
        return target_pattern
    
    def _get_source_pattern(self):
        if self._source_surface is None:
            self._transformed_pattern_cache = (None, None)
            return None
        source_surface = self._source_surface
        
        new_check = (id(source_surface), self.scale, self.rotation)
        check, transformed_pattern = self._transformed_pattern_cache
        # see if the cache is invalid
        if new_check != check:
            # seems like a good rule of thumb to transform the buffer and
            # use the result as surface for scales lower than 1 but for
            # scales bigger than one the life transformation is fast enough
            # this is likely not the best behavior in all scenarios
            transform_buffer = self.scale < 1
            transformed_pattern = self._create_transformed_pattern(source_surface, transform_buffer)
            # cache the results
            self._transformed_pattern_cache = (new_check, transformed_pattern)
        return transformed_pattern
    
    def draw_handler(self, da, cr):
        width = self.get_allocated_width()
        height =  self.get_allocated_height()
        left = math.floor(self.get_hadjustment().get_value())
        top = math.floor(self.get_vadjustment().get_value())
        
        pattern = self._get_source_pattern()
        if pattern is not None:
            cr.set_source(pattern)
            # draws just the visible area
            cr.rectangle(left, top, width, height)
            cr.fill()


class CanvasControls(object):
    """ Simplified interface for Canvas """
    def __init__(self, canvas):
        self.canvas = canvas
    
    def zoomIn(self):
        old = self.canvas.scale
        old = round(old, 2)
        new = old + 0.05
        new = min(16, new)
        
        self.canvas.scale = new
    
    def zoom_out(self):
        old = self.canvas.scale
        old = round(old, 2)
        new = old - 0.05
        new = max(0.05, new)
        self.canvas.scale = new
    
    def zoom_unit(self):
        self.canvas.scale = 1
    
    def zoom_fit(self):
        """ toggles scale to filt"""
        self.canvas.scale_to_fit = not self.canvas.scale_to_fit
    
    def rotate_right(self):
        self.canvas.add_rotation(0.5)
    
    def rotate_left(self):
        self.canvas.add_rotation(-0.5)


class ScrollByHandTool(Gtk.EventBox):
    """ Drag and drop interface to scroll the Image (2 adjustments) when
    the mouse button is pressed and scrolling is possible
    """
    def __init__(self, hadjustment, vadjustment):
        Gtk.EventBox.__init__(self)
        self.add_events(
              Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK # receive motion events only when button1 is pressed
            | Gdk.EventMask.POINTER_MOTION_HINT_MASK
        )
        
        self.hadjustment = hadjustment
        self.vadjustment = vadjustment
        
        vadjustment.connect('value-changed', self.adjustment_value_changed_handler)
        hadjustment.connect('value-changed', self.adjustment_value_changed_handler)
        
        
        self.connect('button-press-event'  , self.button_press_handler)
        self.connect('button-release-event', self.button_release_handler)
        self.connect('motion-notify-event' , self.motion_notify_handler)
        self._scroll_base = None
        self._can_scroll = False
    
    def adjustment_value_changed_handler(self, *args):
        h = self.hadjustment
        v = self.vadjustment
        # "value" field represents the position of the scrollbar, which must
        # be between the "lower" field and "upper - page_size." 
        can_scroll_x = 0 < h.get_upper() - h.get_lower() - h.get_page_size()
        can_scroll_y = 0 < v.get_upper() - v.get_lower() - v.get_page_size()
        
        self._can_scroll = can_scroll_x or can_scroll_y
        if self._can_scroll:
            cursor = Gdk.Cursor.new(Gdk.CursorType.FLEUR)
            self.get_window().set_cursor(cursor)
        else:
            cursor = Gdk.Cursor.new(Gdk.CursorType.ARROW)
            self.get_window().set_cursor(cursor)
            # stop scrolling if doing so
            self._scroll_base = None
        
    def button_press_handler(self, canvas, event):
        if not self._can_scroll:
            #no need to scroll
            self._scroll_base = None
            return
        original_x = self.hadjustment.get_value()
        original_y = self.vadjustment.get_value()
        self._scroll_base = event.x, event.y, original_x, original_y
    
    def motion_notify_handler(self, canvas, event):
        if self._scroll_base is None:
            return
        start_x, start_y, original_x, original_y = self._scroll_base
        now_x, now_y = event.x, event.y
        
        delta_x = now_x - start_x
        delta_y = now_y - start_y
        
        self.hadjustment.set_value(original_x - delta_x)
        self.vadjustment.set_value(original_y - delta_y)
    
    def button_release_handler(self, canvas, event):
        self._scroll_base = None


class PreviewWindow(Gtk.Window):
    """ Display a preview of an image rendered as eps with inks_model as
    source for the PostScript device deviceN.
    """
    def __init__(self, preview_worker, inks_model, image_name=None):
        Gtk.Window.__init__(self)
        
        multitoner_icon_filename = os.path.join(DIRECTORY, 'assets', 'images',
                                            'multitoner_icon.svg')
        multitoner_icon = GdkPixbuf.Pixbuf.new_from_file(multitoner_icon_filename)
        self.set_icon(multitoner_icon)
        
        inks_model.add(self) #subscribe
        self._preview_worker = preview_worker
        
        def destroy_handler(self):
            # remove the PreviewWindow from preview_worker
            preview_worker.remove_client(self.id)
            
            # This fixes a bug where references to the PreviewWindow still
            # existed in the signal handler functions of the actions.
            # (like self.action_rotate_left_handler) GTK did not remove these
            # handlers and thus the PreviewWindow was not garbage collected.
            # So the weakref was never released from the model emitter.
            actions = self._global_actions.list_actions() + self._document_actions.list_actions()
            for action in actions:
                GObject.signal_handlers_destroy(action)
            self.disconnect(destroy_handler_id)
            return True
        destroy_handler_id = self.connect('destroy', destroy_handler)
        
        self.inks_model = weakref(inks_model)
        self.image_name = image_name
        
        self.set_default_size(640, 480)
        self.set_has_resize_grip(True)
        
        self._timeout = None
        self._waiting = False
        self._update_needed = False
        self._no_inks = False
        
        self.grid = Gtk.Grid()
        self.add(self.grid)
        
        self.scrolled = Gtk.ScrolledWindow()
        adjustments = (self.scrolled.get_hadjustment(),
                       self.scrolled.get_vadjustment())
        
        self.canvas = Canvas(*adjustments)
        self.canvas.set_halign(Gtk.Align.CENTER)
        self.canvas.set_valign(Gtk.Align.CENTER)
        self.canvas_ctrl = CanvasControls(self.canvas)
        
        self.scrolled.add(self.canvas)
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        
        scroll_by_hand = ScrollByHandTool(*adjustments)
        scroll_by_hand.add(self.scrolled)
        
        self.menubar, self.toolbar = self._init_menu()
        # synchronize the zoom to fit value
        self._set_zoom_fit_action_active_value(self.canvas.scale_to_fit)
        self.canvas.connect('scale-to-fit-changed', self.scale_to_fit_changed_handler)
        
        # self.grid.attach(self.menubar, 0, 0, 1, 1)
        self.grid.attach(self.toolbar, 0, 1, 1, 1)
        
        self.grid.attach(scroll_by_hand, 0, 3, 1, 1)
        
        self._open_image(image_name)
    
    @property
    def id(self):
        return id(self)
    
    def _set_title(self):
        filename = self.image_name or _('(no image)')
        self.set_title(_('Multitoner Preview: {filename}').format(filename=filename))
    
    @property
    def image_name(self):
        if not hasattr(self, '_image_name'):
            self._image_name = None
        return self._image_name
    
    @image_name.setter
    def image_name(self, value):
        if value == self.image_name:
            return
        self._image_name = value
        self._set_title()
    
    def _make_global_actions(self):
        action_group = ActionGroup('gloabl_actions')
        
        action_group.add_actions([
              ('FileMenu', None, _('File'), None,
               None, None)
            , ('OpenImage', Gtk.STOCK_OPEN, _('Open Image'), 'o',
               _('Open An Image For Preview'), self.action_open_image_handler)
            , ('Quit', Gtk.STOCK_CLOSE, None, 'q',
               _('Close Preview Window'), self.action_close_handler)
        ])
        return action_group
    
    def _make_document_actions(self):
        action_group = ActionGroup('document_actions')
        action_group.add_actions([
              ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('ZoomIn', Gtk.STOCK_ZOOM_IN, None,  'plus',
               _('Zoom In'), self.action_zoom_in_handler)
            , ('ZoomOut', Gtk.STOCK_ZOOM_OUT, None, 'minus',
               _('Zoom Out'), self.action_zoom_out_handler)
            , ('ZoomUnit', Gtk.STOCK_ZOOM_100, None, '1',
               _('Zoom to normal size.'), self.action_zoom_unit_handler)
            ])
        
        action_group.add_icon_actions([
              ('ZoomFit', None, _('Zoom to fit image to window size.'),
                None, self.action_zoom_fit_handler, 'F', Gtk.STOCK_ZOOM_FIT,
                Gtk.ToggleAction)
            , ('RotateRight',  _('Rotate Clockwise'), _('Rotate clockwise.'),
              'object-rotate-right', self.action_rotate_right_handler, 'R')
            , ('RotateLeft', _('Rotate Counterclockwise'), _('Rotate counterclockwise.'),
              'object-rotate-left', self.action_rotate_left_handler, 'L')
            , ('ExportImage', _('Export Image'), _('Export image as EPS file.'),
               'document-save', self.action_export_image_handler, 'E')
            ])
        return action_group
    
    def _set_zoom_fit_action_active_value(self, value):
        zoom_fit_action = self._document_actions.get_action('ZoomFit')
        zoom_fit_action.handler_block_by_func(self.action_zoom_fit_handler)
        zoom_fit_action.set_active(value)
        zoom_fit_action.handler_unblock_by_func(self.action_zoom_fit_handler)
    
    def _init_menu(self):
        self._global_actions = self._make_global_actions()
        self._document_actions = self._make_document_actions()
        self._document_actions.set_sensitive(False)
        
        uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._document_actions)
        uimanager.insert_action_group(self._global_actions)
        menubar = uimanager.get_widget("/MenuBar")
        toolbar = uimanager.get_widget("/ToolBar")
        
        # Add the accelerator group to the toplevel window
        accelgroup = uimanager.get_accel_group()
        self.add_accel_group(accelgroup)
        
        return menubar, toolbar
    
    def _show_message(self, *message):
        window = self.get_toplevel()
        show_message(window, *message)
    
    def on_model_updated(self, inks_model, event, *args):
        if not inks_model.visible_curves:
            self.canvas.receive_surface(None)
            self._no_inks = True
            return
        self._no_inks = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            ink_event = args[1]
            if ink_event not in ('pointUpdate', 'addPoint', 'removePoint',
                                 'setPoints', 'interpolationChanged',
                                 'visibleChanged', 'cmykChanged',
                                 'nameChanged'):
                return
        assert self.inks_model() is inks_model, 'A wrong inks_model instance ' \
                                                'publishes to this PreviewWindow'
        self._request_new_surface()
    
    def _request_new_surface(self):
        """ this will be called very frequently, because generating the
        preview can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(300, self._update_surface)
    
    def _update_surface(self):
        inks_model = self.inks_model()
        # see if the model still exists
        if inks_model is None or not inks_model.visible_curves or self.image_name is None:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed = True
            return False
        
        self._waiting = True
        
        callback = (self._worker_callback, self.image_name)
        self._preview_worker.add_job(self.id, callback, self.image_name, *inks_model.visible_curves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _worker_callback(self, type, image_name, *args):
        self._waiting = False
        if type == 'result':
            message = args[-1]
            if message is not None:
                GLib.idle_add(self._show_message, *message)
            cairo_surface = self._receive_surface(image_name, *args[0:-1])
        else:
            if type == 'error':
                self.image_name = None
            GLib.idle_add(self._show_message, type, *args)
            cairo_surface = None
        
        if cairo_surface is not None:
            self._document_actions.set_sensitive(True)
        else:
            self.image_name = None
            self._document_actions.set_sensitive(False)
        self.canvas.receive_surface(cairo_surface)
    
    def _receive_surface(self, image_name, w, h, rowstride, buf):
        if self._no_inks or self.image_name != image_name:
            # this may receive a surface after all inks are invisible
            # or after the image to display changed
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, rowstride
            )
        
        if self._update_needed:
            # while we where waiting another update became due
            self._update_needed = False
            self._request_new_surface()
        return cairo_surface
    
    def _open_image(self, image_name):
        if image_name is None:
            return
        self.image_name = image_name
        self._request_new_surface()
    
    def ask_for_image(self):
        window = self.get_toplevel()
        filename = show_open_image_dialog(window)
        self._open_image(filename)
    
    # actions
    def action_zoom_in_handler(self, widget):
        self.canvas_ctrl.zoomIn()
    
    def action_zoom_out_handler(self, widget):
        self.canvas_ctrl.zoom_out()
    
    def action_zoom_unit_handler(self, widget):
        self.canvas_ctrl.zoom_unit()
    
    def action_zoom_fit_handler(self, widget):
        self.canvas_ctrl.zoom_fit()
    
    def action_rotate_right_handler(self, widget):
        self.canvas_ctrl.rotate_right()
    
    def action_rotate_left_handler(self, widget):
        self.canvas_ctrl.rotate_left()
    
    def scale_to_fit_changed_handler(self, widget, scale_to_fit):
        self._set_zoom_fit_action_active_value(scale_to_fit)
    
    def action_open_image_handler(self, widget):
        self.ask_for_image()

    def action_close_handler(self, widget):
        self.destroy()
    
    def action_export_image_handler(self, widget):
        inks_model = self.inks_model()
        image_filename = self.image_name
        if image_filename is None or inks_model is None:
            return
        
        window = self.get_toplevel()
        
        eps_filename = show_save_as_eps_dialog(window, image_filename)
        if eps_filename is None:
            return
        
        result, message = model2eps(inks_model, image_filename, eps_filename)
        
        if message:
            window = self.get_toplevel()
            show_message(window, *message)

if __name__ == '__main__':
    """ this can be used as stand alone preview application """
    import sys
    import json
    from model import ModelCurves, ModelInk
    from ghostscript_workers import PreviewWorker
    GObject.threads_init()
    
    if len(sys.argv) > 1:
        mtt_file = sys.argv[1]
        image_name = None
        if len(sys.argv) > 2:
            image_name = sys.argv[-1]
        print (image_name, mtt_file)
        with open(mtt_file) as f:
            data = json.load(f)
        model = ModelCurves(ChildModel=ModelInk, **data)
        preview_worker = PreviewWorker.new_with_pool(processes=1)
        preview_window = PreviewWindow(preview_worker, model, image_name)
        preview_window.connect('destroy', Gtk.main_quit)
        preview_window.show_all()
        Gtk.main()
    else:
        print (_('Need a .mtt file as first argument and optionally an image file as last argument.'))
