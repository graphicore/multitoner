#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import PIL.Image as Image
import json

from epstool import EPSTool
from model import ModelCurves, ModelInk

__all__ = ['open_image', 'model2eps', 'mtt2eps']

# just a preparation for i18n
def _(string):
    return string

def open_image(filename):
    """ returns (eps_tool, notice, error)
    
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
        if im.mode != 'L':
            # Display a message in the ui process. Earn that reproducing
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
    return make_eps(model.visibleCurves, image_filename)
    
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
