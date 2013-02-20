#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import with_statement
import mom.codec as codec
import PIL.Image as image
import sys

"""Extract the image of a Photoshop generated Multitone EPS file"""


def extractBoundingBox(chars):
    pure = chars[len('%%BoundingBox:'):].strip();
    return tuple(map(int, pure.split(' ')[0:4]))
    
def extractBinary(lines):
    # consider the first two lines and the last line as garbage
    # this only makes sense when the layout is as follows:
    # lines = [
    #    '%%BeginBinary:       1847\r\n'
    #    'beginimage\r\n'
    #    … here is binary data in ascii85 until '~>'
    #    '%%EndBinary\r\n'
    # ]
    if('%%BeginBinary' not in lines[0]):
        raise ValueError('Wrong format, first line must begin with "%%BeginBinary"');
    if(lines[1].find('beginimage') != 0):
        raise ValueError('Wrong format, seccond line must begin with "beginimage"');
    if('%%EndBinary' not in lines[-1]):
        raise ValueError('Wrong format, last line must contain "%%EndBinary"');
    data = ''.join(lines[1:]);
    end = data.find('~>');
    if end == -1:
        raise ValueError('Wrong format, data does not contain an end marker "~>"');
    data = data[len('beginimage'):data.find('~>')];
    return codec.base85_decode(data)
    
    
def getImageData(path):
    boundingBox = None
    binary = None
    with open(path, 'r') as eps:
        storebinary = False;
        for line in eps:
            if line.find('%%BoundingBox:') == 0 and not boundingBox:
                boundingBox = line;
            if line.find('%%BeginBinary:') == 0 and not binary:
                storebinary = True
                binary = []
            if(storebinary):
                binary.append(line)
            if line.find('%%EndBinary') == 0:
                storebinary = False
                break;
    if(boundingBox):
        boundingBox = extractBoundingBox(boundingBox)
    if(binary):
        binary = extractBinary(binary)
    size = boundingBox[2] * boundingBox[3];
    if binary and len(binary) != size:
        raise ValueError(('Extracted data is {0} bytes long but should be '
            + '{1} bytes long. According to the boundingbox {2}'
            ).format( len(binary), size, boundingBox)
        )
    return (boundingBox, binary)

def saveImage(name, size, data):
    # L is greyscale mode
    img = image.new('L', size)
    img.putdata(data)
    img.save(name)

if __name__ == '__main__':
    filename = sys.argv[1];
    boundingBox, data  = getImageData(filename);
    if(not boundingBox or not data):
        raise ValueError("Wasn't able to extract data.");
    saveImage(filename + '.tif', boundingBox[2:], data);
