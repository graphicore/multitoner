#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import sys
from gi.repository import Gtk, GObject, Gdk, GLib
from gtk_extended import ActionGroup
import cairo
from emitter import Emitter
from weakref import ref as weakref
import math
from compatibility import repair_gsignals
from dialogs import show_open_image_dialog, show_message, show_save_as_eps_dialog
from mtt2eps import model2eps

__all__ = ['PreviewWindow']

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
    __gsignals__ = repair_gsignals({
        'scale-to-fit-changed': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                                 # the value of scaleToFit
                                 GObject.TYPE_BOOLEAN, ))
    })
    
    
    def __init__(self, *args):
        Gtk.Viewport.__init__(self, *args)
        
        self._transformedPatternCache = (None, None)
        
        self.sourceSurface = None
        
        self._center = None
        self._restoringCenter = False
        self._timers = {}
        
        self.da = Gtk.DrawingArea()
        self.add(self.da)
        self._initEventHandlers()
        
        self.drawCounter = 0
    
    def _initEventHandlers(self):
        self.da.connect('draw' , self.onDraw)
        self.da.add_events(
            Gdk.EventMask.STRUCTURE_MASK # needed for configure-event
        )
        self.da.connect('configure-event', self.configureHandler)
        self.get_vadjustment().connect(
            'value-changed', self.adjustmentValueChangedHandler)
        self.get_hadjustment().connect(
            'value-changed', self.adjustmentValueChangedHandler)
        
        # this will keep the center of the image in the center of the window
        # when the window is beeing resized
        self.add_events(
            Gdk.EventMask.STRUCTURE_MASK # needed for configure-event
        )
        def onRealize(widget, *args):
            """ 
            closure to connect to window when it establishes this widget
            """
            window = widget.get_toplevel()
            window.connect('configure-event', self.toplevelConfigureHandler)
            
            parent = widget.get_parent()
            parent.connect('size-allocate', self.parentSizeAllocateHandler)
            
            widget.disconnect(realize_handler_id)
        # save realize_handler_id for the closure of onRealize 
        realize_handler_id = self.connect('realize' , onRealize)
    
    def receiveSurface(self, surface):
        self.sourceSurface = surface
        if not hasattr(self, '_scale') or self.scaleToFit:
            self.setFittingScale()
        else:
            self._resize()
        self.da.queue_draw()
    
    def _resize(self):
        # needs bounding box width and height after all transformations
        if self.sourceSurface is not None:
            matrix = self._getScaledMatrix()
            w, h, _, _ = self._getSurfaceExtents(matrix, self.sourceSurface)
        else:
            w = h = 0
        self.da.set_size_request(w, h)
    
    def configureHandler(self, widget, event):
        """
        the configure event signals when the DrawingArea got resized
        happens after receiveSurface and can be handled immediately
        """
        if not self.scaleToFit:
            self._restoreCenter()
    
    """ when the toplevel window got resized """
    toplevelConfigureHandler = configureHandler
    
    def parentSizeAllocateHandler(self, parent, allocation):
        if self.scaleToFit:
            self._setFittingScale(allocation.width, allocation.height)
    
    def adjustmentValueChangedHandler(self, adjustment):
        self._saveCenter()
    
    def _saveCenter(self):
        if self._restoringCenter == True:
            return
        center = (
        #   (scrollbar position                 + screen width                 / 2)) / image width
            (self.get_hadjustment().get_value() + (self.get_allocated_width()  / 2)) / self.da.get_allocated_width()
        #   (scrollbar position                 + screen height                / 2)) / image height
          , (self.get_vadjustment().get_value() + (self.get_allocated_height() / 2)) / self.da.get_allocated_height()
        )
        self._center = center
        return center
    
    def _restoreCenter(self):
        if self._center is None:
            return
        self._restoringCenter = True
        try:
            h, v = self._center
            #      image width                    * center of view - screen width   / 2
            left = self.da.get_allocated_width()  * h - self.get_allocated_width()  / 2
            #      image height                   * center of view - screen height  / 2
            top  = self.da.get_allocated_height() * v - self.get_allocated_height() / 2
            self.get_hadjustment().set_value(left)
            self.get_vadjustment().set_value(top)
        finally:
            self._restoringCenter = False
    
    def _setScale(self, value):
        """ will set the new scale"""
        if self.scale == value:
            return
        self._scale = value
        self._saveCenter()
        self._resize()
        self.da.queue_draw()
    
    @property
    def rotation(self):
        return getattr(self, '_rotation', 0)
    
    @rotation.setter
    def rotation(self, value):
        """ between 0 and 2 will be multiplied with PI => radians """
        self._rotation = value % 2
        if self.scaleToFit:
            self.setFittingScale()
        self._resize()
        self.da.queue_draw()
    
    def addRotation(self, value):
        self.rotation += value
    
    @property
    def scale(self):
        return getattr(self, '_scale', 1.0)
    
    @scale.setter
    def scale(self, value):
        """ will turn off scale to fit and set the new scale"""
        self.scaleToFit = False
        self._setScale(value)
    
    @property
    def scaleToFit(self):
        return getattr(self, '_scaleToFit', True)
    
    @scaleToFit.setter
    def scaleToFit(self, value):
        old = self.scaleToFit
        self._scaleToFit = not not value
        if self._scaleToFit != old:
            self.emit('scale-to-fit-changed', self._scaleToFit)
        if self._scaleToFit:
            self.setFittingScale()
    
    def setFittingScale(self):
        parent = self.get_parent()
        if parent is None:
            return
        parent_allocation = parent.get_allocation()
        self._setFittingScale(parent_allocation.width, parent_allocation.height)
    
    def _setFittingScale(self, available_width, available_height):
        """
        set the scale to a value that makes the image fit exactly into
        available_width and available_height
        """
        if self.sourceSurface is None:
            return
        # needs unscaled width and unscaled height, so the matrix must not
        # be scaled, the rotation however is needed
        matrix = self._getRotatedMatrix()
        source_width, source_height, _, _ = self._getSurfaceExtents(matrix, self.sourceSurface)
        try:
            aspect_ratio = source_width / source_height
            available_aspect_ratio = available_width / available_height
        except ZeroDivisionError:
            self._setScale(1)
        else:
            if aspect_ratio > available_aspect_ratio:
                # fit to width
                self._setScale(available_width / source_width)
            else: 
                # fit to height
                self._setScale(available_height / source_height)
    
    def _getBBox(self, matrix, x1, y1, x2, y2):
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
    
    def _getBBOxExtents(self, matrix, x1, y1, x2, y2):
        """
        apply matrix to the rectangle defined by x1, y1, x2, y2
        returns width, height, offset_x, offset_y of the bounding box
        this is used to determine the space needed to draw the surface
        and to move the contents back into view using the offsets
        """
        x1, y1, x2, y2 = self._getBBox(matrix, x1, y1, x2, y2)
        w = int(math.ceil(x2-x1))
        h = int(math.ceil(y2-y1))
        offset_x, offset_y = x1, y1
        return w, h, offset_x, offset_y
    
    def _getSurfaceExtents(self, matrix, surface):
        """
        get the extents and offsets of surface after the application
        of matrix
        """
        x1, y1, x2, y2 = 0, 0, surface.get_width(), surface.get_height()
        return self._getBBOxExtents(matrix, x1, y1, x2, y2)
    
    def _getRotatedMatrix(self):
        """ matrix with rotation but without scale"""
        matrix = cairo.Matrix()
        matrix.rotate(self.rotation * math.pi)
        # rotate?
        return matrix
    
    def _getScaledMatrix(self):
        """ matrix with rotation and scale"""
        matrix = self._getRotatedMatrix()
        matrix.scale(self.scale, self.scale)
        return matrix
    
    def _createTransformedPattern(self, sourceSurface, transform_buffer=True):
        """
        returns cairo pattern to set as source of a cairo context
        
        When transform_buffer is False the returned pattern will have all
        necessary transformations applied to its affine transformation
        matrix. The source buffer, however will be the original sourceSurface.
        So drawing that pattern will apply all transformations life, this
        can result in a lot of cpu work when the pattern is drawn multiple
        times.
        
        When transform_buffer is True, the returned pattern will be a
        pattern with no extra transformations applied. Instead its surface
        will hold the image data after all transformations have been applied.
        """
        # calculate width and height using the new matrix
        matrix = self._getScaledMatrix()
        w, h, offset_x, offset_y = self._getSurfaceExtents(matrix, sourceSurface)
        
        # finish the transformation matrix by translating the pattern
        # back into view using the offsets the transformation created.
        # IMPORTANT: the normal translate method of a cairo.Matrix applies
        # before all other transformations. Here we need it to be applied
        # after all transformations, hence the usage of multiply
        translate_matrix = cairo.Matrix()
        translate_matrix.translate(-offset_x, -offset_y)
        matrix = matrix.multiply(translate_matrix)
        
        source_pattern = cairo.SurfacePattern(sourceSurface)
        # cairo.SurfacePattern uses inverted matrices, see the docs for pattern
        matrix.invert()
        source_pattern.set_matrix(matrix)
        if not transform_buffer:
            return source_pattern
        # the result of this can be cached and will speedup the display
        # for large images alot, because all transformations will be applied
        # just once not on every onDraw event
        target_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        # the context to draw on the new surface
        co = cairo.Context(target_surface)
        # draw to target_surface
        co.set_source(source_pattern)
        co.paint()
        target_pattern = cairo.SurfacePattern(target_surface)
        return target_pattern
    
    def _getSourcePattern(self):
        if self.sourceSurface is None:
            self._transformedPatternCache = (None, None)
            return None
        sourceSurface = self.sourceSurface
        
        new_check = (id(sourceSurface), self.scale, self.rotation)
        check, transformed_pattern = self._transformedPatternCache
        # see if the cache is invalid
        if new_check != check:
            # seems like a good rule of thumb to transform the buffer and
            # use the result as surface for scales lower than 1 but for
            # scales bigger than one the life transformation is fast enough
            # this is likely not the best behavior in all scenarios
            transform_buffer = self.scale < 1
            transformed_pattern = self._createTransformedPattern(sourceSurface, transform_buffer)
            # cache the results
            self._transformedPatternCache = (new_check, transformed_pattern)
        return transformed_pattern
    
    def onDraw(self, da, cr):
        # if not hasattr(self, '_draw_counter')
        #     self._draw_counter = 0
        # print ('onDraw', self._draw_counter)
        # self._draw_counter += 1
        
        width = self.get_allocated_width()
        height =  self.get_allocated_height()
        left = math.floor(self.get_hadjustment().get_value())
        top = math.floor(self.get_vadjustment().get_value())
        
        pattern = self._getSourcePattern()
        if pattern is not None:
            cr.set_source(pattern)
            # draws just the visible area
            cr.rectangle(left, top, width, height)
            cr.fill()

class CanvasControls(Emitter):
    def __init__(self, canvas):
        self.canvas = canvas
    
    def zoomIn(self):
        old = self.canvas.scale
        old = round(old, 2)
        new = old + 0.05
        new = min(16, new)
        
        self.canvas.scale = new
    
    def zoomOut(self):
        old = self.canvas.scale
        old = round(old, 2)
        new = old - 0.05
        new = max(0.05, new)
        self.canvas.scale = new
    
    def zoomUnit(self):
        old = self.canvas.scale
        self.canvas.scale = 1
    
    def zoomFit(self):
        """ toggles scale to filt"""
        self.canvas.scaleToFit = not self.canvas.scaleToFit
    
    def rotateRight(self):
        self.canvas.addRotation(0.5)
    
    def rotateLeft(self):
        self.canvas.addRotation(-0.5)

class ScrollByHandTool(Gtk.EventBox):
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
        
        vadjustment.connect('value-changed', self.adjustmentValueChangedHandler)
        hadjustment.connect('value-changed', self.adjustmentValueChangedHandler)
        
        
        self.connect('button-press-event'  , self.buttonPressHandler)
        self.connect('button-release-event', self.buttonReleaseHandler)
        self.connect('motion-notify-event' , self.motionNotifyHandler)
        self._scrollBase = None
        self._canScroll = False
    
    def adjustmentValueChangedHandler(self, *args):
        h = self.hadjustment
        v = self.vadjustment
        # "value" field represents the position of the scrollbar, which must
        # be between the "lower" field and "upper - page_size." 
        can_scroll_x = 0 < h.get_upper() - h.get_lower() - h.get_page_size()
        can_scroll_y = 0 < v.get_upper() - v.get_lower() - v.get_page_size()
        
        self._canScroll = can_scroll_x or can_scroll_y
        if self._canScroll:
            cursor = Gdk.Cursor.new(Gdk.CursorType.FLEUR)
            self.get_window().set_cursor(cursor)
        else:
            cursor = Gdk.Cursor.new(Gdk.CursorType.ARROW)
            self.get_window().set_cursor(cursor)
            # stop scrolling if doing so
            self._scrollBase = None
        
    def buttonPressHandler(self, canvas, event):
        if not self._canScroll:
            #no need to scroll
            self._scrollBase = None
            return
        original_x = self.hadjustment.get_value()
        original_y = self.vadjustment.get_value()
        self._scrollBase = event.x, event.y, original_x, original_y
    
    def motionNotifyHandler(self, canvas, event):
        if self._scrollBase is None:
            return
        start_x, start_y, original_x, original_y = self._scrollBase
        now_x, now_y = event.x, event.y
        
        delta_x = now_x - start_x
        delta_y = now_y - start_y
        
        self.hadjustment.set_value(original_x - delta_x)
        self.vadjustment.set_value(original_y - delta_y)
    
    def buttonReleaseHandler(self, canvas, event):
        self._scrollBase = None


class PreviewWindow(Gtk.Window):
    def __init__(self, previewWorker, inksModel, imageName=None):
        Gtk.Window.__init__(self)
        inksModel.add(self) #subscribe
        self._previewWorker = previewWorker
        
        def destroy(self):
            # remove the PreviewWindow from previewWorker
            previewWorker.remove_client(self, self.id)
            
            # This fixes a bug where references to the PreviewWindow still
            # existed in the signal handler functions of the actions.
            # (like self.actionRotateLeftHandler) GTK did not remove these
            # handlers and thus the PreviewWindow was not garbage collected.
            # So the weakref was never released from the model emitter.
            actions = self._globalActions.list_actions() + self._documentActions.list_actions()
            for action in actions:
                GObject.signal_handlers_destroy(action)
            self.disconnect(destroy_handler_id)
            return True
        destroy_handler_id = self.connect('destroy', destroy)
        
        self.inksModel = weakref(inksModel)
        self.imageName = imageName
        
        self.set_default_size(640, 480)
        self.set_has_resize_grip(True)
        
        self._timeout = None
        self._waiting = False
        self._update_needed = False
        self._noInks = False
        
        self.grid = Gtk.Grid()
        self.add(self.grid)
        
        self.scrolled = Gtk.ScrolledWindow()
        adjustments = (self.scrolled.get_hadjustment(),
                       self.scrolled.get_vadjustment())
        
        self.canvas = Canvas(*adjustments)
        self.canvas.set_halign(Gtk.Align.CENTER)
        self.canvas.set_valign(Gtk.Align.CENTER)
        self.canvasCtrl = CanvasControls(self.canvas)
        self.canvasCtrl.add(self) # subscribe
        
        self.scrolled.add(self.canvas)
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        
        scrollByHand = ScrollByHandTool(*adjustments)
        scrollByHand.add(self.scrolled)
        
        self.menubar, self.toolbar = self._initMenu()
        # synchronize the zoom to fit value
        self._setZoomFitActionActiveValue(self.canvas.scaleToFit)
        self.canvas.connect('scale-to-fit-changed', self.scaleToFitChangedHandler)
        
        # self.grid.attach(self.menubar, 0, 0, 1, 1)
        self.grid.attach(self.toolbar, 0, 1, 1, 1)
        
        self.grid.attach(scrollByHand, 0, 3, 1, 1)
        
        self._openImage(imageName)
    
    @property
    def id(self):
        return id(self)
    
    def _setTitle(self):
        filename = self.imageName or _('(no image)')
        self.set_title(_('Multitoner Tool Preview: {filename}').format(filename=filename))
    
    @property
    def imageName(self):
        if not hasattr(self, '_imageName'):
            self._imageName = None
        return self._imageName
    
    @imageName.setter
    def imageName(self, value):
        if value == self.imageName:
            return
        self._imageName = value
        self._setTitle()
    
    def _makeGlobalActions(self):
        actionGroup = ActionGroup('gloabl_actions')
        
        actionGroup.add_actions([
              ('FileMenu', None, _('File'), None,
               None, None)
            , ('OpenImage', Gtk.STOCK_OPEN, _('Open Image'), 'o',
               _('Open An Image For Preview'), self.actionOpenImageHandler)
            , ('Quit', Gtk.STOCK_CLOSE, None, 'q',
               _('Close Preview Window'), self.actionCloseHandler)
        ])
        return actionGroup
    
    def _makeDocumentActions(self):
        actionGroup = ActionGroup('document_actions')
        actionGroup.add_actions([
              ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('ZoomIn', Gtk.STOCK_ZOOM_IN, None,  'plus',
               _('Zoom In'), self.actionZoomInHandler)
            , ('ZoomOut', Gtk.STOCK_ZOOM_OUT, None, 'minus',
               _('Zoom Out'), self.actionZoomOutHandler)
            , ('ZoomUnit', Gtk.STOCK_ZOOM_100, None, '1',
               _('Zoom to Normal Size'), self.actionZoomUnitHandler)
            ])
        
        actionGroup.add_icon_actions([
              ('ZoomFit', None, _('Zoom To Fit Image To Windowsize'),
                None, self.actionZoomFitHandler, 'F', Gtk.STOCK_ZOOM_FIT,
                Gtk.ToggleAction)
            , ('RotateRight',  _('Rotate Clockwise'), _('Rotate Clockwise'),
              'object-rotate-right', self.actionRotateRightHandler, 'R')
            , ('RotateLeft', _('Rotate Counterclockwise'), _('Rotate Counterclockwise'),
              'object-rotate-left', self.actionRotateLeftHandler, 'L')
            , ('ExportImage', _('Export Image'), _('Export Image as EPS file'),
               'document-save', self.actionExportImageHandler, 'E')
            ])
        return actionGroup
    
    def _setZoomFitActionActiveValue(self, value):
        zoomFitAction = self._documentActions.get_action('ZoomFit')
        zoomFitAction.handler_block_by_func(self.actionZoomFitHandler)
        zoomFitAction.set_active(value)
        zoomFitAction.handler_unblock_by_func(self.actionZoomFitHandler)
    
    def _initMenu(self):
        self._globalActions = self._makeGlobalActions()
        self._documentActions = self._makeDocumentActions()
        self._documentActions.set_sensitive(False)
        
        self.UIManager = uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._documentActions)
        uimanager.insert_action_group(self._globalActions)
        menubar = uimanager.get_widget("/MenuBar")
        toolbar = uimanager.get_widget("/ToolBar")
        
        # Add the accelerator group to the toplevel window
        accelgroup = uimanager.get_accel_group()
        self.add_accel_group(accelgroup)
        
        return menubar, toolbar
    
    def showMessage(self, *message):
        window = self.get_toplevel()
        show_message(window, *message)
    
    def onModelUpdated(self, inksModel, event, *args):
        if len(inksModel.visibleCurves) == 0:
            self.canvas.receiveSurface(None)
            self._noInks = True
            return
        self._noInks = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            inkEvent = args[1]
            if inkEvent not in ('pointUpdate', 'addPoint', 'removePoint',
                                'setPoints', 'interpolationChanged',
                                'visibleChanged', 'cmykChanged',
                                'nameChanged'):
                return
        assert self.inksModel() is inksModel, 'A wrong inksModel instance publishes to this PreviewWindow'
        self._requestNewSurface()
    
    def _requestNewSurface(self):
        """ this will be called very frequently, because generating the
        preview can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(300, self._updateSurface)
    
    def _updateSurface(self):
        inksModel = self.inksModel()
        # see if the model still exists
        if inksModel is None or len(inksModel.visibleCurves) == 0 or self.imageName is None:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed = True
            return False
        
        self._waiting = True
        
        callback = (self._workerAnswerHandler, self.imageName)
        self._previewWorker.add_job(self.id, callback, self.imageName, *inksModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _workerAnswerHandler(self, type, imageName, *args):
        self._waiting = False
        if type == 'result':
            message = args[-1]
            if message is not None:
                GLib.idle_add(self.showMessage, *message)
            cairo_surface = self._receiveSurface(imageName, *args[0:-1])
        else:
            if type == 'error':
                self.imageName = None
            GLib.idle_add(self.showMessage, type, *args)
            cairo_surface = None
        
        if cairo_surface is not None:
            self._documentActions.set_sensitive(True)
        else:
            self.imageName = None
            self._documentActions.set_sensitive(False)
        self.canvas.receiveSurface(cairo_surface)
    
    def _receiveSurface(self, imageName, w, h, rowstride, buf):
        if self._noInks or self.imageName != imageName:
            # this may receive a surface after all inks are invisible
            # or after the image to display changed
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, rowstride
            )
        
        # print ('_receiveSurface >>>> ', w, h)
        if self._update_needed:
            # while we where waiting another update became due
            self._update_needed = False
            self._requestNewSurface()
        return cairo_surface
    
    def _openImage(self, imageName):
        if imageName is None:
            return
        self.imageName = imageName
        self._requestNewSurface()
    
    def askForImage(self):
        window = self.get_toplevel()
        filename = show_open_image_dialog(window)
        self._openImage(filename)
    
    # actions
    def actionZoomInHandler(self, widget):
        self.canvasCtrl.zoomIn()
    
    def actionZoomOutHandler(self, widget):
        self.canvasCtrl.zoomOut()
    
    def actionZoomUnitHandler(self, widget):
        self.canvasCtrl.zoomUnit()
    
    def actionZoomFitHandler(self, widget):
        self.canvasCtrl.zoomFit()
    
    def actionRotateRightHandler(self, widget):
        self.canvasCtrl.rotateRight()
    
    def actionRotateLeftHandler(self, widget):
        self.canvasCtrl.rotateLeft()
    
    def scaleToFitChangedHandler(self, widget, scaleToFit):
        self._setZoomFitActionActiveValue(scaleToFit)
    
    def actionOpenImageHandler(self, widget):
        self.askForImage()

    def actionCloseHandler(self, widget):
        self.destroy()
    
    def actionExportImageHandler(self, widget):
        inksModel = self.inksModel()
        image_filename = self.imageName
        if image_filename is None or inksModel is None:
            return
        
        window = self.get_toplevel()
        
        eps_filename = show_save_as_eps_dialog(window, image_filename)
        if eps_filename is None:
            return
        
        result, message = model2eps(inksModel, image_filename, eps_filename)
        
        if message:
            window = self.get_toplevel()
            show_message(window, *message)

if __name__ == '__main__':
    import sys
    import json
    from model import ModelCurves, ModelInk
    from ghostscript_workers import PreviewWorker
    GObject.threads_init()
    
    if len(sys.argv) > 1:
        mttFile = sys.argv[1]
        imageName = None
        if len(sys.argv) > 2:
            imageName = sys.argv[-1]
        print (imageName, mttFile)
        with open(mttFile) as f:
            data = json.load(f)
        model = ModelCurves(ChildModel=ModelInk, **data)
        previewWorker = PreviewWorker.new_with_pool(processes=1)
        previewWindow = PreviewWindow(previewWorker, model, imageName)
        previewWindow.connect('destroy', Gtk.main_quit)
        previewWindow.show_all()
        Gtk.main()
    else:
        print (_('Need a .mtt file as first argument and optionally an image file as last argument.'))
