#!/usr/bin/python
# -*- coding: utf-8 -*-

from Worker import Worker
from array import array
from epstool import EPSTool
from GhostScriptRunner import GhostScriptRunner

class GradientWorker(Worker):
    def __init__(self):
        super(GradientWorker, self).__init__()
        self._epsTool = EPSTool()
        gradientBin = array('B', xrange(0, 256))
        # FIXME: there seems to be a problem wit a 0 byte at the beginning
        # this must be in the ascii85 representation i suppose
        #gradientBin.reverse()
        
        # the input gradient is 256 pixels wide and 1 pixel height
        # we don't need more data and scale this on display
        self._epsTool.setImageData(gradientBin.tostring(), (256, 1))
        self._gs = GhostScriptRunner()
        
    def addJob(self, callback, *tints):
        self._epsTool.setColorData(*tints)
        eps = self._epsTool.create()
        job = (eps, )
        self._queue.put( (job, callback) )
        
    def _run(self, eps):
        return self._gs.run(eps)
