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
    def __init__(self):
        self.__subscriptions = WeakSet()
    
    def __iter__(self):
        for item in self.__subscriptions:
            yield item
    
    def add(self, thing):
        self.__subscriptions.add(thing)
    
    def discard(self, thing):
        self.__subscriptions.discard(thing)
    
    def remove(self, thing):
        self.__subscriptions.remove(thing)
