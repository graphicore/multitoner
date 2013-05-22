#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from emitter import Emitter

# just a preparation for i18n
def _(string):
    return string

class ModelException(Exception):
    pass

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
    def __init__(self, points=[(0,0), (1,1)], interpolation='monotoneCubic', displayColor=(0,0,0)):
        super(ModelCurve, self).__init__()
        self.interpolation = interpolation
        self.points = points
        self.displayColor = displayColor
    
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
    def pointsValue(self):
        return sorted(point.xy for point in self._points)
    
    @property
    def displayColor(self):
        return self._displayColor
    
    @displayColor.setter
    def displayColor(self, value):
        self._displayColor = value
        self.triggerOnModelUpdated('displayColorChanged')
    
class ModelCurves(Model):
    def __init__(self, curves=[], ChildModel = ModelCurve):
        super(ModelCurves, self).__init__()
        self.ChildModel = ChildModel
        self.curves = curves
    
    @property
    def curves(self):
        return tuple(self._curves)
    
    @curves.setter
    def curves(self, curves=[]):
        self._curves = []
        for curve in curves:
            self._appendCurve(**curve)
        self.triggerOnModelUpdated('setCurves')
    
    def __len__(self):
        return len(self._curves)
    
    def reorderByIdList(self, ids):
        currentOrder = map(id, self._curves)
        if ids == currentOrder:
            # the same order was supplied
            return;
        idSet = set(ids)
        if len(idSet) != len(self._curves):
            raise ModelException(
                'Reorder: list of ids is not long enough. Len is {0} but should be {1}'
                .format(len(ids), len(self._curves))
            )
        seen = set()
        newOrder = []
        for mid in ids:
            if mid in seen:
                raise ModelException('Having a duplicate id in ordering {0}'.format(mid))
            seen.add(mid)
            try:
                currentPos = currentOrder.index(mid)
            except ValueError, e:
                raise ModelException('Model not found by id {0}'.format(mid))
            newOrder.append(self._curves[currentPos])
        self._curves = newOrder
        self.triggerOnModelUpdated('reorderedCurves')
    
    def onModelUpdated(self, curveModel, *args):
        self.triggerOnModelUpdated('curveUpdate', curveModel, *args)
    
    def _appendCurve(self, **args):
        model = self.ChildModel(**args)
        model.add(self) # subscribe
        self._curves.append(model)
        return model
    
    def appendCurve(self, **args):
        model = self._appendCurve(**args)
        self.triggerOnModelUpdated('appendCurve', model)
    
    def removeCurve(self, model):
        self._curves.remove(model)
        self.triggerOnModelUpdated('removeCurve', model)

class ModelTint(ModelCurve):
    def __init__(self, name=_('(unnamed)'), cmyk=(0.0, 0.0, 0.0, 0.0), **args):
        super(ModelTint, self).__init__(**args)
        self.name = name
        self.cmyk = cmyk
    
    def onModelUpdated(self, curveModel, *args):
        self.triggerOnModelUpdated('curveUpdate', curveModel, *args)
    
    @property
    def name(self):
        return self._name
    
    @name.setter
    def name(self, value):
        self._name = value
        self.triggerOnModelUpdated('nameChanged')
    
    @property
    def cmyk(self):
        return tuple(self._cmyk)
    
    @cmyk.setter
    def cmyk(self, value):
        self._cmyk = list(value)
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def c(self):
        return self._cmyk[0]
    
    @c.setter
    def c(self, value):
        self._cmyk[0] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def m(self):
        return self._cmyk[1]
    
    @m.setter
    def m(self, value):
        self._cmyk[1] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def y(self):
        return self._cmyk[2]
    
    @y.setter
    def y(self, value):
        self._cmyk[2] = value
        self.triggerOnModelUpdated('cmykChanged')
    
    @property
    def k(self):
        return self._cmyk[3]
    
    @k.setter
    def k(self, value):
        self._cmyk[3] = value
        self.triggerOnModelUpdated('cmykChanged')
