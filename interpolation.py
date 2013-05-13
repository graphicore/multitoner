#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import numpy as np
# http://docs.scipy.org/doc/scipy/reference/tutorial/interpolate.html
from scipy import interpolate 

# just a preparation for i18n
def _(string):
    return string

class InterpolationStrategy(object):
    
    @property
    def name(self):
        raise NotImplementedError('Name must be defined by subclass')
    
    @property
    def description(self):
        raise NotImplementedError('Description must be defined by subclass')
    
    def _function(*args):
        raise NotImplementedError('_function must be defined by subclass')
    
    def __init__(self, points):
        self.setPoints(points)
    
    def setPoints(self, points):
        if len(points) < 2:
            raise CurveException('Need at least two points');
        pts = zip(*points)
        self._x = np.array(pts[0], dtype=float)
        self._y = np.array(pts[1], dtype=float)
    
    def __call__(self, xs):
        """
        takes an np array of x values and returns an np array of the same
        length as the input array representing the corresponding y values
        """
        return self._function(xs)

class InterpolatedSpline(InterpolationStrategy):
    """
    Produces a smooth spline between the input points
    """
    name = _('Spline')
    description = _('Very smooth but very self-willed, too.')
    def setPoints(self, points):
        super(InterpolatedSpline, self).setPoints(points)
        # The number of data points must be larger than the spline degree k
        k = 5#3
        M = len(self._x)
        if k >= M:
            k = M-1
        self._function = interpolate.UnivariateSpline(self._x,self._y,s=0,k=k)

class InterpolatedMonotoneCubic(InterpolationStrategy):
    """
    Produces a smoothend curve between the input points using a monotonic
    cubic interpolation PCHIP: Piecewise Cubic Hermite Interpolating Polynomia
    """
    name = _('Monotone Cubic')
    description = _('Smooth and does what you say. Not as smooth as Spline.')
    def setPoints(self, points):
        super(InterpolatedMonotoneCubic, self).setPoints(points)
        self._function = interpolate.pchip(self._x, self._y)

class InterpolatedLinear(InterpolationStrategy):
    """
    Produces a lineaer interpolation between the input points
    """
    name = _('Linear')
    description = _('Just straight lines between control points.')
    def _function(self, xs):
        return np.interp(xs, self._x, self._y)

# this is to keep the list ordered
interpolationStrategies = (
    ('monotoneCubic', InterpolatedMonotoneCubic),
    ('spline'       , InterpolatedSpline),
    ('linear'       , InterpolatedLinear)
)
# this is for faster lookup
interpolationStrategiesDict = dict(interpolationStrategies)
