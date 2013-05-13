#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from emitter import Emitter

class Model(Emitter):
    def triggerOnModelUpdated(self, *args):
        for item in self:
            item.onModelUpdated(self, *args)

class ModelControlPoint(Model):
    def __init__(self, xy):
        super(ModelControlPoint, self).__init__()
        self.xy = xy
    
    @property
    def xy(self):
        return self._xy
    
    @xy.setter
    def xy(self, xy):
        xy = (
            max(0, min(1, xy[0])),
            max(0, min(1, xy[1]))
        )
        if not hasattr(self, '_xy') or xy != self._xy:
            self._xy = xy
            self.triggerOnModelUpdated()

class ModelCurve(Model):
    def __init__(self, points=[(0,0), (1,1)], interpolation='monotoneCubic'):
        super(ModelCurve, self).__init__()
        self.interpolation = interpolation
        self.points = points
    
    def onModelUpdated(self, cp_model, *args):
        self.triggerOnModelUpdated('pointUpdate', cp_model, *args)
    
    def _addPoint(self, point):
        model = ModelControlPoint(point)
        model.add(self) # subscribe
        self._points.append(model)
        return model
    
    def addPoint(self, point):
        model = self._addPoint(point)
        self.triggerOnModelUpdated('addPoint', model)
        # as a 'setter' this doesn't return
        # return model
    
    def removePoint(self, model):
        if len(self._points) == 2:
            return
        self._points.remove(model)
        self.triggerOnModelUpdated('removePoint', model)
    
    @property
    def points(self):
        # this returns an unordered tuple of the point models
        # the _points list is not returned because changing the _points
        # list would change the model value and that's not intended as part
        # of the interface
        return tuple(self._points)
        
    @points.setter
    def points(self, points):
        self._points = []
        for point in points:
            self._addPoint(point)
        self.triggerOnModelUpdated('setPoints')
    
    @property
    def interpolation(self):
        return self._interpolation
    
    @interpolation.setter
    def interpolation(self, interpolation):
        self._interpolation = interpolation
        self.triggerOnModelUpdated('interpolationChanged')
    
    @property
    def value(self):
        return sorted(point.xy for point in self._points)

class ModelCurves(Model):
    def __init__(self, curves=[]):
        super(ModelCurves, self).__init__()
        self.curves = curves
    
    @property
    def curves(self):
        return tuple(self._curves)
    
    @curves.setter
    def curves(self, curves=[]):
        self._curves = []
        for curve in curves:
            self._appendCurve(*curve)
        self.triggerOnModelUpdated('setCurves')
    
    def onModelUpdated(self, curveModel, *args):
        self.triggerOnModelUpdated('curveUpdate', curveModel, *args)
    
    def _appendCurve(self, *args):
        model = ModelCurve(*args)
        model.add(self) # subscribe
        self._curves.append(model)
        return model
    
    def appendCurve(self, *args):
        model = self._appendCurve(*args)
        self.triggerOnModelUpdated('appendCurve', model)
    
    def removeCurve(self, model):
        self._curves.remove(model)
        self.triggerOnModelUpdated('removeCurve', model)
