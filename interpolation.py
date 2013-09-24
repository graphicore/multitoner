#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import numpy as np
# http://docs.scipy.org/doc/scipy/reference/tutorial/interpolate.html
from scipy import interpolate 

__all__ = ['InterpolationStrategy', 'InterpolatedSpline', 'InterpolatedMonotoneCubic'
           'InterpolatedLinear', 'interpolation_strategies',
           'interpolation_strategies_dict']

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
        self.set_points(points)
    
    def set_points(self, points):
        if len(points) < 2:
            raise CurveException('Need at least two points');
        pts = list(zip(*points))
        # in python3 pts needs the conversion to list because in python3
        # zip returns iterators resulting in:
        # TypeError: 'zip' object is not subscriptable
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
    def set_points(self, points):
        super(InterpolatedSpline, self).set_points(points)
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
    def set_points(self, points):
        super(InterpolatedMonotoneCubic, self).set_points(points)
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
interpolation_strategies = (
    ('monotoneCubic', InterpolatedMonotoneCubic),
    ('spline'       , InterpolatedSpline),
    ('linear'       , InterpolatedLinear)
)
# this is for faster lookup
interpolation_strategies_dict = dict(interpolation_strategies)
