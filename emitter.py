#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from weakref import WeakSet

class Emitter(object):
    """
        simple event subscription
        important:
            1. this is uses a set, so there is no guaranteed order
            2. the subscriber needs to implement all callbacks of the actual Emitter
        
        to subscribe use emitterObj.add
        to unsubscribe use emitterObj.remove or emitterObj.discard or
           delete all references to the subscriber
    """
    @property
    def _subscriptions(self):
        if not hasattr(self, '_Emitter__subscriptions'):
            self.__subscriptions = WeakSet()
        return self.__subscriptions
    
    def add(self, thing):
        self._subscriptions.add(thing)
    
    def discard(self, thing):
        self._subscriptions.discard(thing)
    
    def remove(self, thing):
        self._subscriptions.remove(thing)
    
    def _getstate(self, state):
        # this is what the __ makes with atrribute names : _{0}{1}.format(ClassName, MethodName)
        if '_Emitter__subscriptions' in state:
            del state['_Emitter__subscriptions'] # remove the WeakSet
    
    def __getstate__(self):
        state = self.__dict__.copy() # copy the dict since we change it
        return self._getstate(_getstate)
    
    # no need for since this Class can handle a missing _Emitter__subscriptions
    # def __setstate__():
