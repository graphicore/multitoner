#!/usr/bin/python
# -*- coding: utf-8 -*-


from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk, GObject
import cairo
from epstool import EPSTool
import PIL.Image as Image
from weakref import ref as Weakref
from multiprocessing import Pool
import ctypes as c
from model import ModelInk

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
 
def work(filename, inks):
    """
    This runs in its own process, ideally, then there is no threading
    problem with ghostscript
    """
    global imageName, epsTool
    if filename != imageName:
        imageName = filename
        epsTool = EPSTool()
        im = Image.open(imageName)
        print ('image mode', im.mode, 'epsTool.setImageData ...')
        epsTool.setImageData(im.tostring(), im.size)
        print ('epsTool.setImageData ... DONE!')
    
    print ('work with', inks)
    inks = [ModelInk(**t) for t in inks]
    
    epsTool.setColorData(*inks)
    eps = epsTool.create()
    with open(imageName + '.tsst.eps', 'w') as f:
        f.write(eps)
    print ('gs.run.eps')
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
    
    def addJob(self, callback, imageName, *inks):
        cb = lambda result: self.callback(callback, result)
        
        print (inks)
        inks = [t.getArgs() for t in inks]
        self.pool.apply_async(work, args=(imageName, inks), callback=cb)

class PreviewDrawinArea(Gtk.Layout):
    def __init__(self):
        Gtk.Layout.__init__(self)
        self.surface = None
        self.connect('draw' , self.onDraw)
    @staticmethod
    def onDraw(self, cr):
        cairo_surface = self.surface
        h = self.get_hadjustment().get_value()
        v = self.get_vadjustment().get_value()
        print ('draw', cairo_surface, h, v)
        if cairo_surface is not None:
            cr.set_source_surface(cairo_surface, -h , -v)
        cr.paint()
        return True
        
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
        
        self.da = PreviewDrawinArea()
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.add(self.da)
        self.add(self.scrolled)
        self._previewWorker = PreviewWorker()
        self._requestNewSurface(inksModel)
    
    def onModelUpdated(self, inksModel, event, *args):
        if len(inksModel.visibleCurves) == 0:
            self.da.surface = None
            self.da.queue_draw()
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
        self.da.set_size(w, h)
        if self._noInks:
            # this may receive a surface after all inks are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, w * 4
            )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            inksModel = self._update_needed() # its a weakref
            self._update_needed = None
            if inksModel is not None:
                self._requestNewSurface(inksModel)
        
        self.da.surface = cairo_surface
        self.da.queue_draw()
