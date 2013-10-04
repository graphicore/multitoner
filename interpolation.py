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

from __future__ import division, print_function, unicode_literals

import numpy as np
from scipy import interpolate # http://docs.scipy.org/doc/scipy/reference/tutorial/interpolate.html


__all__ = ['InterpolationStrategy', 'InterpolatedSpline', 'InterpolatedMonotoneCubic'
           'InterpolatedLinear', 'interpolation_strategies',
           'interpolation_strategies_dict']


# just a preparation for i18n
def _(string):
    return string


class InterpolationStrategy(object):
    """ Abstract base class for all interpolation strategies. """
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
        """ Take an np array of x values and return an np array of the same
        length as the input array representing the corresponding y values.
        """
        return self._function(xs)


class InterpolatedSpline(InterpolationStrategy):
    """ Produces a smooth spline between the input points """
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
    """ Produces a smoothend curve between the input points using a monotonic
    cubic interpolation PCHIP: Piecewise Cubic Hermite Interpolating Polynomia.
    """
    name = _('Monotone Cubic')
    description = _('Smooth and does what you say. Not as smooth as Spline.')
    def set_points(self, points):
        super(InterpolatedMonotoneCubic, self).set_points(points)
        self._function = interpolate.pchip(self._x, self._y)


class InterpolatedLinear(InterpolationStrategy):
    """ Produces a lineaer interpolation between the input points. """
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
