#!/usr/bin/python
# -*- coding: utf-8 -*-

from epstool import EPSTool
from array import array
from multiprocessing import Pool, cpu_count
import ctypes as c
from compatibility import range

gs = None
def initializer(*args):
    """ 
    import and initialize ghostscript only in a worker process
    the main process doesn't need it
    """
    from GhostScriptRunner import GhostScriptRunner
    global gs
    gs = GhostScriptRunner()

def work(job):
    """
    This runs in its own process, ideally, then there is no threading
    problem with ghostscript
    """
    r = gs.run(job)
    # need to transport the result as a string
    result = r[0], r[1], r[2].raw
    return result

class GradientWorker(object):
    def __init__(self):
        self.pool = Pool(initializer=initializer)
        
        self._epsTool = EPSTool()
        gradientBin = array('B', range(0, 256))
        # the input gradient is 256 pixels wide and 1 pixel height
        # we don't need more data and scale this on display
        self._epsTool.setImageData(gradientBin.tostring(), (256, 1))
    
    def callback(self, callback, user_data, result):
        """
        this restores the buffer data from string and runs the callback
        """
        buf = c.create_string_buffer(result[2])
        args = user_data + (result[0], result[1], buf)
        callback(*args)
    
    def addJob(self, callback, *inks):
        self._epsTool.setColorData(*inks)
        eps = self._epsTool.create()
        def cb(result):
            self.callback(callback[0], callback[1:], result)
        self.pool.apply_async(work, args=(eps, ), callback=cb)
