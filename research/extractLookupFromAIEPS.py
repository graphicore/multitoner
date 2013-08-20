#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import with_statement
import mom.codec as codec
import PIL.Image as image
import sys

"""Extract the Indexed Colorspace Lookup Table of an Adobe Illustratore
generated Multitone EPS file.

This was just used for comparison purposes.
"""


def extractBoundingBox(chars):
    pure = chars[len('%%BoundingBox:'):].strip();
    return tuple(map(int, pure.split(' ')[0:4]))
    
def extractBinary(lines):
    data = ''.join(map(str.strip, lines));
    data = data[data.find('<~')+2:data.find('~>')];
    return codec.base85_decode(data)
    
def getLookupData(path):
    binary = None
    with open(path, 'r') as eps:
        storebinary = False;
        for line in eps:
            if line.find('/Lookup <~') != -1 and not binary:
                storebinary = True
                binary = []
            if(storebinary):
                binary.append(line)
            if line.find('~>') != -1:
                storebinary = False
                break;
    if(binary):
        return extractBinary(binary)
    return binary

if __name__ == '__main__':
    filename = sys.argv[1];
    data  = getLookupData(filename);
    print data
