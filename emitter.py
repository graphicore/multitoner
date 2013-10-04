#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2013 by Lasse Fister <commander@graphicore.de>
# 
# This file is part of Multitoner.
#
# Multitoner is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Multitoner is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division

from weakref import WeakSet

__all__ = ['Emitter']


class Emitter(object):
    """Simple events.
    
    The subscribers are stored in a weakref.WeakSet, so:
        - Deleting all references to a subscriberend will end the subscription.
        - There will never be more than one subscription per object, no
          matter how often it was subscribed via add()
        - There's no guaranteed order of execution. E.g. the last subscriber
          may get called first.
    
    IMPORTANT:  The subscriber needs to implement all callbacks of the
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
        """ Remove thing from the set of subscribers if present. """
        self._subscriptions.discard(thing)
    
    def remove(self, thing):
        """ Remove thing from the set of subscribers.
        
        raises KeyError if thing is not present
        
        """
        self._subscriptions.remove(thing)
    
    @classmethod
    def _cleanstate(Cls, state):
        """ pickle protocol: Remove the weakset when pickling. """
        # this is what the __ makes with atrribute names:
        #    _{0}{1}.format(ClassName, MethodName)
        if '_Emitter__subscriptions' in state:
            del state['_Emitter__subscriptions'] # remove the WeakSet
    
    def __getstate__(self):
        state = self.__dict__.copy() # copy the dict since we change it
        return self._cleanstate(state)
    
    # def __setstate__():
    # no need for since this class can handle a missing _Emitter__subscriptions
