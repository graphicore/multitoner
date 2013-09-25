#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division

from weakref import WeakSet

__all__ = ['Emitter']


class Emitter(object):
    """simple event subscription
    
    The subscribers are stored in a weakref.WeakSet, so:
        - Deleting all references to a subscriberend will end the subscription.
        - There will never be more than one subscription per object, no
          matter how often it was subscribed via add()
        - There's no guaranteed order of execution. E.g. the last subscriber
          may get called first.
    
    IMPORTANT:  the subscriber needs to implement all callbacks of the
    concrete Emitter.
    
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
        """ Subscribe to this emmiter.
        
        Be warned that the Emitter expects certain callback methods to exist
        in the subscribing object. The name of the methods and the behavior
        depends on the concrete implementation of the emitter.
        
        """
        self._subscriptions.add(thing)
    
    def discard(self, thing):
        """ Remove thing from the set of subscribers if present
        
        """
        self._subscriptions.discard(thing)
    
    def remove(self, thing):
        """ remove thing from the set of subscribers
        
        raises KeyError if thing is not present
        
        """
        self._subscriptions.remove(thing)
    
    def _getstate(self, state):
        """ pickle protocol: remove the weakset when pickling """
        # this is what the __ makes with atrribute names:
        #    _{0}{1}.format(ClassName, MethodName)
        if '_Emitter__subscriptions' in state:
            del state['_Emitter__subscriptions'] # remove the WeakSet
    
    def __getstate__(self):
        state = self.__dict__.copy() # copy the dict since we change it
        return self._getstate(_getstate)
    
    # def __setstate__():
    # no need for since this Class can handle a missing _Emitter__subscriptions
