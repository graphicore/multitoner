#!/usr/bin/python
# -*- coding: utf-8 -*-


from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk, GObject
import cairo
from PreviewWorker import PreviewWorker
from weakref import ref as Weakref
import math

# just a preparation for i18n
def _(string):
    return string

class Canvas(Gtk.Viewport):
    def __init__(self, *args):
        Gtk.Viewport.__init__(self, *args)
        
        self.scale = 1
        
        self.surface = None
        self.widh = 0
        self.height = 0
        
        self.da = Gtk.DrawingArea()
        self.add(self.da)
        self.da.connect('draw' , self.onDraw)
    
    def receiveSurface(self, surface, width, height):
        self.surface = surface
        self.width = width
        self.height = height
        self._resize()
        self.da.queue_draw()
    
    def _resize(self):
        self.da.set_size_request(
            math.ceil(self.width * self.scale),
            math.ceil(self.height * self.scale)
        )
    
    def onDraw(self, da, cr):
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
        
        self.scrolled = Gtk.ScrolledWindow()
        adjustments = (self.scrolled.get_hadjustment(),
                       self.scrolled.get_vadjustment())
        
        self.canvas = Canvas(*adjustments)
        self.canvas.set_halign(Gtk.Align.CENTER)
        self.canvas.set_valign(Gtk.Align.CENTER)
        
        self.scrolled.add(self.canvas)
        
        self.add(self.scrolled)
        self._previewWorker = PreviewWorker()
        self._requestNewSurface(inksModel)
    
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
        
        scale = self.canvas.scale = 1
        self.canvas.receiveSurface(cairo_surface, w, h)
