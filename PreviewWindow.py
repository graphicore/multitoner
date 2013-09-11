#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk, GObject, Gdk
import cairo
from PreviewWorker import PreviewWorker
from emitter import Emitter
from weakref import ref as Weakref
import math

# just a preparation for i18n
def _(string):
    return string

UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action="EditMenu">
      <menuitem action='ZoomIn' />
      <menuitem action='ZoomOut' />
      <menuitem action='ZoomUnit' />
      <menuitem action='ZoomFit' />
    </menu>
  </menubar>
  <toolbar name="ToolBar">
      <toolitem action='ZoomIn' />
      <toolitem action='ZoomOut' />
      <toolitem action='ZoomUnit' />
      <toolitem action='ZoomFit' />
  </toolbar>
</ui>
"""

class Canvas(Gtk.Viewport):
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
            parent_allocation = self.get_parent().get_allocation()
            self._scaleToFit(parent_allocation.width, parent_allocation.height)
        else:
            self._resize()
        self.da.queue_draw()
    
    def _resize(self):
        # needs bounding box width and height after all transformations
        matrix = self._getScaledMatrix()
        w, h, _, _ = self._getSurfaceExtents(matrix, self.sourceSurface)
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
        if self.scaleToFit and self.sourceSurface is not None:
            self._scaleToFit(allocation.width, allocation.height)
    
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
        return getattr(self, '_scaleToFitFlag', True)
    
    @scaleToFit.setter
    def scaleToFit(self, value):
        self._scaleToFitFlag = not not value
        if self._scaleToFitFlag and self.sourceSurface is not None:
            parent_allocation = self.get_parent().get_allocation()
            self._scaleToFit(parent_allocation.width, parent_allocation.height)
    
    def _scaleToFit(self, available_width, available_height):
        """
        set the scale to a value that makes the image fit exactly into
        available_width and available_height
        """
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
    
    def _createTransformedPattern(self, sourceSurface, cache=True):
        """
        returns cairo pattern to set as source of a cairo context
        
        When cache is False the returned pattern will have all necessary
        translations applied to its affine transformation matrix its source,
        however will be the original sourceSurface. So drawing that pattern
        will apply all transformations then, this can result in a lot of
        cpu work when the pattern is drawn multiple times.
        
        When cache is True, the returned pattern will be a pattern with no
        special transformations applied. Instead its surface will hold the
        image data after all transformations have been applied to it.
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
        if not cache:
            return source_pattern
        # the result of this can be cached and will speedup the display
        # fo large images alot, because all transformations will be applied
        # just once not on every onDraw event
        target_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        # the context to draw on the new surface
        co = cairo.Context(target_surface)
        # draw to target_surface
        co.set_source(source_pattern)
        # create a pattern with the cached transformation
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
            transformed_pattern = self._createTransformedPattern(sourceSurface, True)
            # cache the results
            self._transformedPatternCache = (new_check, transformed_pattern)
        return transformed_pattern
    
    def onDraw(self, da, cr):
        print ('onDraw', self.drawCounter)
        self.drawCounter+=1
        
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
        self.canvas.addRotation(0.5)

class PreviewWindow(Gtk.Window):
    def __init__(self, inksModel, imageName):
        Gtk.Window.__init__(self)
        inksModel.add(self) #subscribe
        self.imageName = imageName
        
        self.set_title(_('Multitoner Tool preview: {filename}').format(filename=imageName))
        self.set_default_size(640, 480)
        self.set_has_resize_grip(True)
        
        
        self._timeout = None
        self._waiting = False
        self._update_needed = None
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
        
        self.menubar, self.toolbar = self._initMenu()
        
        self.grid.attach(self.menubar, 0, 0, 1, 1)
        self.grid.attach(self.toolbar, 0, 1, 1, 1)
        
        self.grid.attach(self.scrolled, 0, 3, 1, 1)
        
        self._previewWorker = PreviewWorker()
        self._requestNewSurface(inksModel)
    
    def _makeDocumentActions(self):
        actionGroup = Gtk.ActionGroup('document_actions')
        actionGroup.add_actions([
              ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('ZoomIn', Gtk.STOCK_ZOOM_IN, None,  'plus',
               None, self.actionZoomInHandler)
            , ('ZoomOut', Gtk.STOCK_ZOOM_OUT, None, 'minus',
               None, self.actionZoomOutHandler)
            , ('ZoomUnit', Gtk.STOCK_ZOOM_100, None, '0',
               None, self.actionZoomUnitHandler)
            , ('ZoomFit', Gtk.STOCK_ZOOM_FIT, None, 'F',
               None, self.actionZoomFitHandler)
            ])
        return actionGroup
    
    def _initMenu(self):
        self._documentActions = self._makeDocumentActions()
        self.UIManager = uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._documentActions)
        menubar = uimanager.get_widget("/MenuBar")
        toolbar = uimanager.get_widget("/ToolBar")
        
        # Add the accelerator group to the toplevel window
        accelgroup = uimanager.get_accel_group()
        self.add_accel_group(accelgroup)
        
        return menubar, toolbar
    
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
        self._requestNewSurface(inksModel)
    
    def _requestNewSurface(self, inksModel):
        """ this will be called very frequently, because generating the
        preview can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._updateSurface, Weakref(inksModel))
    
    def _updateSurface(self, weakrefModel):
        inksModel = weakrefModel()
        # see if the model still exists
        if inksModel is None or len(inksModel.visibleCurves) == 0:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed = weakrefModel
            return False
        
        self._waiting = True
        
        callback = (self._receiveSurface, )
        self._previewWorker.addJob(callback, self.imageName, *inksModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, w, h, buf):
        if self._noInks:
            # this may receive a surface after all inks are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, w * 4
            )
        print ('_receiveSurface >>>> ', cairo_surface)
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            inksModel = self._update_needed() # its a weakref
            self._update_needed = None
            if inksModel is not None:
                self._requestNewSurface(inksModel)
        
        self.canvas.receiveSurface(cairo_surface)
    
    # actions
    def actionZoomInHandler(self, widget):
        self.canvasCtrl.zoomIn()
    
    def actionZoomOutHandler(self, widget):
        self.canvasCtrl.zoomOut()
    
    def actionZoomUnitHandler(self, widget):
        self.canvasCtrl.zoomUnit()
    
    def actionZoomFitHandler(self, widget):
        self.canvasCtrl.zoomFit()
