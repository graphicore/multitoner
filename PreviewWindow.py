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
    </menu>
  </menubar>
  <toolbar name="ToolBar">
      <toolitem action='ZoomIn' />
      <toolitem action='ZoomOut' />
      <toolitem action='ZoomUnit' />
  </toolbar>
</ui>
"""

class Canvas(Gtk.Viewport):
    def __init__(self, *args):
        Gtk.Viewport.__init__(self, *args)
        
        self.surface = None
        self.width = 0
        self.height = 0
        
        self.scaleToFit = False
        
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
    
    def receiveSurface(self, surface, width, height):
        self.surface = surface
        self.width = width
        self.height = height
        
        if not hasattr(self, '_scale'):
            parent_allocation = self.get_parent().get_allocation()
            self._scaleToFit(parent_allocation.width, parent_allocation.height)
        else:
            self._resize()
        self.da.queue_draw()
    
    def _resize(self):
        print ('resize')
        self.da.set_size_request(
            math.ceil(self.width * self.scale),
            math.ceil(self.height * self.scale)
        )
    
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
            self._scheduleScaleToFit(allocation.width, allocation.height)
    
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
    
    @property
    def scale(self):
        return getattr(self, '_scale', 1)
    
    @scale.setter
    def scale(self, value):
        if self.scale == value:
            return
        self._scale = value
        self._saveCenter()
        self._resize()
        self.da.queue_draw()
    
    def _schedule(self, callback, time, *args, **kwds):
        timer = self._timers.get(callback, None)
        if timer is not None:
            # remove the old timer
            GObject.source_remove(timer)
        # schedule a new execution
        timer = GObject.timeout_add(time, callback, *args, **kwds)
        # remember the new timer
        self._timers[callback] = timer
    
    def _scheduleScaleToFit(self, width, height):
        self._schedule(self._scaleToFit, 300, width, height)
    
    def _scaleToFit(self, available_width, available_height):
        try:
            aspect_ratio = self.width / self.height
            available_aspect_ratio = available_width / available_height
        except ZeroDivisionError:
            self.scale = 1
        else:
            if aspect_ratio > available_aspect_ratio:
                # fit to width
                self.scale = available_width/self.width
            else: 
                # fit to height
                self.scale = available_height/self.height
    
    def onDraw(self, da, cr):
        print ('onDraw', self.drawCounter)
        self.drawCounter+=1
        
        width = self.get_allocated_width()
        height =  self.get_allocated_height()
        left = math.floor(self.get_hadjustment().get_value())
        top = math.floor(self.get_vadjustment().get_value())
        surface = self.surface
        if surface is not None:
            pattern = cairo.SurfacePattern(surface)
            matrix = cairo.Matrix()
            matrix.scale(self.scale, self.scale)
            matrix.invert()
            pattern.set_matrix(matrix)
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
        pass

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
        
        scaler = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 16.0, 0.05)
        scaler.set_digits(2)
        scaler.set_draw_value(True)
        scaler.set_value(1)
        def setScale(*args):
            self.canvas.scale = scaler.get_value()
        scaler.connect('value-changed', setScale)
        
        self.grid.attach(self.menubar, 0, 0, 1, 1)
        self.grid.attach(self.toolbar, 0, 1, 1, 1)
        self.grid.attach(scaler,  0, 2, 1, 1)
        scaler.set_halign(Gtk.Align.FILL)
        
        self.grid.attach(self.scrolled, 0, 3, 1, 1)
        
        self._previewWorker = PreviewWorker()
        self._requestNewSurface(inksModel)
    
    def _makeDocumentActions(self):
        actionGroup = Gtk.ActionGroup('document_actions')
        actionGroup.add_actions([
              ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('ZoomIn', Gtk.STOCK_ZOOM_IN, _('Zoom In'),  '<Ctrl>plus',
               None, self.actionZoomInHandler)
            , ('ZoomOut', Gtk.STOCK_ZOOM_OUT, _('Zoom Out'), '<Ctrl>minus',
               None, self.actionZoomOutHandler)
            , ('ZoomUnit', Gtk.STOCK_ZOOM_100, _('Zoom 100%'), '<Ctrl>minus',
               None, self.actionZoomUnitHandler)
               # missing: Gtk.STOCK_ZOOM_100, Gtk.STOCK_ZOOM_FIT
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
            self.canvas.receiveSurface(None, 0, 0)
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
        print ('_receiveSurface')
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
        
        self.canvas.receiveSurface(cairo_surface, w, h)
    
    # actions
    def actionZoomInHandler(self, widget):
        self.canvasCtrl.zoomIn()
    
    def actionZoomOutHandler(self, widget):
        self.canvasCtrl.zoomOut()
    
    def actionZoomUnitHandler(self, widget):
        self.canvasCtrl.zoomUnit()
