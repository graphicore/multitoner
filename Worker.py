#!/usr/bin/python
# -*- coding: utf-8 -*-

from gi.repository import GObject
import threading
from Queue import Queue

class Worker(object):
    def __init__(self):
        self._queue = Queue(maxsize=100)
        self._t = threading.Thread(target=self._work)
        self._t.daemon = True
        self._t.start()
    
    def _work(self):
        ''' waits until something is in the queue'''
        for job, callback in iter(self._queue.get, None):
            result = self._run(*job)
            GObject.idle_add(* (callback + (result)) )
    
    def _run(self):
        raise NotImplementedError('the _run method must be implemented')
