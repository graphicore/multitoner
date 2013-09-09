#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from epstool import EPSTool
import PIL.Image as Image
from multiprocessing import Pool
import ctypes as c
from model import ModelInk

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
    # with open(imageName + '.tsst.eps', 'w') as f:
    #     f.write(eps)
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
        inks = [t.getArgs() for t in inks]
        self.pool.apply_async(work, args=(imageName, inks), callback=cb)
