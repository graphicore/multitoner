#!/usr/bin/python
# -*- coding: utf-8 -*-


from __future__ import division

from gi.repository import Gtk, GObject
import cairo
from epstool import EPSTool
import PIL.Image as Image
from weakref import ref as Weakref
from multiprocessing import Pool
import ctypes as c
from model import ModelTint

# just a preparation for i18n
def _(string):
    return string

# in the process
gs = None
imageName = None
epsTool = None

def initializer(*args):
    """ 
    import and initialize ghostscript only in a worker process
    the main process doesn't need it
    """
    from GhostScriptRunner import GhostScriptRunner
    global gs
    gs = GhostScriptRunner()
 
def work(filename, tints):
    """
    This runs in its own process, ideally, then there is no threading
    problem with ghostscript
    """
    global imageName, epsTool
    if filename != imageName:
        imageName = filename
        epsTool = EPSTool()
        im = Image.open(imageName)
        print 'image mode', im.mode
        epsTool.setImageData(im.tostring(), im.size)
    
    print tints
    tints = [ModelTint(**t) for t in tints]
    
    epsTool.setColorData(*tints)
    eps = epsTool.create()
    # eps = open(imageName + '.eps').read()
    with open(imageName + '.tst.eps', 'w') as f:
        f.write(eps)
    r = gs.run(eps)
    # need to transport the result as a string
    result = r[0], r[1], r[2].raw
    return result
# end in the process

class PreviewWorker(object):
    def __init__(self):
        self.pool = Pool(initializer=initializer, processes=1)
    
    def callback(self, callback, result):
        """
        this restores the buffer data from string and runs the callback
        """
        buf = c.create_string_buffer(result[2])
        args = callback[1:] + (result[0], result[1], buf)
        callback[0](*args)
    
    def addJob(self, callback, imageName, *tints):
        cb = lambda result: self.callback(callback, result)
        
        print tints
        tints = [t.getArgs() for t in tints]
        self.pool.apply_async(work, args=(imageName, tints), callback=cb)

class PreviewDrawinArea(Gtk.DrawingArea):
    def __init__(self):
        Gtk.DrawingArea.__init__(self)
        self.surface = None
        self.connect('draw' , self.onDraw)
    @staticmethod
    def onDraw(self, cr):
        cairo_surface = self.surface
        print 'draw', cairo_surface
        if cairo_surface is not None:
            cr.set_source_surface(cairo_surface, 0 , 0)
        cr.paint()
        return True
        
class PreviewWindow(Gtk.Window):
    def __init__(self, tintsModel, imageName):
        Gtk.Window.__init__(self)
        tintsModel.add(self) #subscribe
        self.imageName = imageName
        
        self.set_title(_('Multitoner Tool preview: {filename}').format(filename=imageName))
        self.set_default_size(640, 480)
        self.set_has_resize_grip(True)
        
        
        self._timeout = None
        self._waiting = False
        self._update_needed = None
        self._noTints = False
        
        self.da = PreviewDrawinArea()
        self.add(self.da)
        self._previewWorker = PreviewWorker()
    
    def onModelUpdated(self, tintsModel, event, *args):
        if len(tintsModel.visibleCurves) == 0:
            self.da.surface = None
            self.da.queue_draw()
            self._noTints = True
            return
        self._noTints = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            tintEvent = args[1]
            if tintEvent not in ('pointUpdate', 'addPoint', 'removePoint',
                                 'setPoints', 'interpolationChanged',
                                 'visibleChanged', 'cmykChanged'):
                return
        self._requestNewSurface(tintsModel)
    
    def _requestNewSurface(self, tintsModel):
        """ this will be called very frequently, because generating the
        preview can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._updateSurface, Weakref(tintsModel))
    
    def _updateSurface(self, weakrefModel):
        tintsModel = weakrefModel()
        # see if the model still exists
        if tintsModel is None or len(tintsModel.visibleCurves) == 0:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed = weakrefModel
            return False
        
        self._waiting = True
        
        callback = (self._receiveSurface, )
        self._previewWorker.addJob(callback, self.imageName, *tintsModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, w, h, buf):
        print '_receiveSurface'
        self.da.set_size_request(w, h)
        if self._noTints:
            # this may receive a surface after all tints are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, w * 4
            )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            tintsModel = self._update_needed() # its a weakref
            self._update_needed = None
            if tintsModel is not None:
                self._requestNewSurface(tintsModel)
        
        self.da.surface = cairo_surface
        self.da.queue_draw()
