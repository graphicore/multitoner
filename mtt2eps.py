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

import PIL.Image as Image
from PIL import ExifTags

import json

from epstool import EPSTool
from model import ModelCurves, ModelInk


__all__ = ['open_image', 'model2eps', 'mtt2eps']


# just a preparation for i18n
def _(string):
    return string

class ImageManipulation(object):
    # see rectify_rotation
    for _exif_orientation_tag, search in ExifTags.TAGS.iteritems(): 
        if search == 'Orientation':
            del search
            break
    # see rectify_rotation
    _orientation_transpose_methods = {
          3: Image.ROTATE_180
        , 6: Image.ROTATE_270
        , 8: Image.ROTATE_90
        }
    
    @classmethod
    def rectify_rotation(cls, image):
        """
        Rotate the image physically to the orientation the exif tag for
        orientation suggest. Return the original image if no rotation was
        performed, otherwise return a rotated copy of image.
        
        A JPEG image might have an exif tag that tells the viewer how it
        should be rotatet. Usually the camera writes that tag depending
        on how it was held when taking the photo.
        
        from http://stackoverflow.com/a/11543365/1315369
        """
        # only present in JPEGs
        if not hasattr(image, '_getexif'):
            return image
        
        exif = image._getexif()
        # has no exif tags
        if exif is None:
            return image
        orientation = exif.get(cls._exif_orientation_tag, None) # 1, 3, 6, 8
        if orientation in cls._orientation_transpose_methods:
            transpose_method = cls._orientation_transpose_methods[orientation]
            return image.transpose(transpose_method)
        return image

def open_image(filename):
    """ Return (eps_tool, notice, error)
    
    eps_tool: an instance of eps_tool loaded with the data of the image at filename
    notice: a tuple with a notice for the user or None
    error: None or if an error occured an error tuple to return with work,
           then eps_tool and notice must not be used.
    """
    error = notice = eps_tool = None
    try:
        im = Image.open(filename)
    except IOError as e:
        error = ('error'
                , _('Can\'t open image for preview {0}.').format(filename)
                , _('Message: {0} {1}').format(e, type(e))
                )
    else:
        im = ImageManipulation.rectify_rotation(im)
        if im.mode != 'L':
            # Display a message in the ui process. Reproducing
            # the result relies on the method used to convert here. It's
            # better to have a grayscale image as input.
            notice = ('notice'
                     , _('Converted image to grayscale')
                     , _('From Python Imaging Library (PIL) mode "{0}".').format(im.mode)
                     )
            im = im.convert('L')
        eps_tool = EPSTool()
        eps_tool.set_image_data(im.tostring(), im.size)
        
    return eps_tool, notice, error


def make_eps(inks, image_filename):
    eps_tool, notice, error = open_image(image_filename)
    eps_tool.set_color_data(*inks)
    return eps_tool.create(), notice, error


def make_eps_from_model(model, image_filename):
    return make_eps(model.visible_curves, image_filename)


def open_mtt_file(mtt_filename):
    with open(mtt_filename, 'r') as f:
        data = json.load(f)
    model = ModelCurves(ChildModel=ModelInk, **data)
    return model


def model2eps(model, image_filename, eps_filename):
    eps, notice, error = make_eps_from_model(model, image_filename)
    if error is None:
        with open(eps_filename, 'w') as f:
            f.write(eps)
        return True, notice
    else:
        return False, error


def mtt2eps(mtt_filename, image_filename, eps_filename):
    model = open_mtt_file(mtt_filename)
    return model2eps(model, image_filename, eps_filename)


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 4:
        result, message = mtt2eps(*sys.argv[1:])
        if message is not None:
            print(message[1].title() + ':', *message[1:])
        if result:
            print('Done!')
        else:
            print('Failed!')
    else:
        print(_('Give me three arguments: source mtt-filename, source image-filename, destination eps-filename'))
