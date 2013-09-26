#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals, print_function

from string import Template
import binascii
from datetime import datetime
import numpy as np

from interpolation import interpolation_strategies_dict

__all__ = ['EPSTool', 'EPSToolException']

init_colors = Template("""gsave % clipping path gsave
%note: 4.2 More Free Advice
%%+ ...
%%+ 2. Do not rely on the initial graphic state having a default current color value
%%+ of “black”. Your code should explicitly call “0 setgray” or “0 0 0 1
%%+ setcmykcolor” to set the current color to black. This will allow separation
%%+ applications to properly separate black objects in your document, by rede-
%%+ fining setgray and setcmykcolor

newpath 0 0 moveto
0 1 lineto 1 1 lineto 1 0 lineto 0 0 lineto clip
newpath 1 setlinewidth

%note: this for repeats for every process color used
$initProcessColors

%note: the following repeats for every custom color used
$initCustomColors

grestore % matches clipping path gsave, so this restores the old clipping path if there was any
""")


eps_template = Template("""%!PS-Adobe-3.0 EPSF-3.0
%%Creator: Multitoner V0.0
%%Title: no title given
%%CreationDate: $CreationDate
%%BoundingBox: 0 0 $width $height
%%HiResBoundingBox: 0 0 $width $height
%%SuppressDotGainCompensation

%note: the following three comments are described in 5044.ColorSep_Conf.pdf
$DSCColors

%%EndComments
%%BeginProlog
%%EndProlog
%%BeginSetup
%%EndSetup

%note: PLRM page 603: pushes a copy of the current graphics state on the
%%+ graphics state stack
gsave % EPS gsave


%note begin: pushes dict on the dictionary stack, making it the current 
%%+ dictionary so this is our 'local namespace' now

40 dict begin

%note: define level3: true when we can lookup languagelevel and its >= 3
%%+ so read 'at least level 3'
/level3
  systemdict /languagelevel known
  {languagelevel 3 ge}
  {false}
  ifelse
def

level3 not {
    (This image needs PostScript Level 3) print quit
} if

%%BeginObject: duotone

gsave % Image Header gsave

$initColors

%note: this is the size of the current image
/rows $height def
/cols $width def
%note: this is needed to scale the image correctly, it has 38x38 pixels
%%+ the currentmarix will be multiplied to this, the question is what sets
%%+ the unit of the currentmatrix to a value that represents pixels
%%+ using rows and cols here would be nice, too. I think.
$width $height scale

$DuotoneNames

$DuotoneCMYKValues

%note: this is the duotoneColorspace with a fallback to DeviceCMYK
[
  /Indexed
  [
    /DeviceN
    DuotoneNames
    [ /DeviceCMYK ]
    {
      % this procedure is written by (c) 2013 Lasse Fister <commander@graphicore.de>
      %%+ make CMYK Values from The Indexed colorspace when DeviceN is not availabe
      %%+ use an array to lookup the the CMYK "analogies" of the spot colors.
      %%+ note: from a colormanagement perspective it would be better to have XYZ
      %%+ values for the spot colors or some other device independent colorspace.
      [0.0 0.0 0.0 0.0]
      0 1 DuotoneCMYKValues length 1 sub
      {
        dup
        %stack: input0 ... inputs result index index
        DuotoneCMYKValues exch get exch
        %stack: input0 ... inputs result cmykvalue0 index
        DuotoneCMYKValues length exch sub 2 add -1 roll exch
        %stack: inputs result input0 cmykvalue0
        2 copy 0 get mul 3 -2 roll
        2 copy 1 get mul 3 -2 roll
        2 copy 2 get mul 3 -2 roll
               3 get mul
        5 -1 roll
        %stack: inputs C0 M0 Y0 K0 result 
        dup dup 3 get 4 -1 roll add 3 exch put
        dup dup 2 get 4 -1 roll add 2 exch put
        dup dup 1 get 4 -1 roll add 1 exch put
        dup dup 0 get 4 -1 roll add 0 exch put
        %stack inputs result
      }
      for
      % don't let the values be bigger than 1.0
      dup 0 get 1 gt {  dup 0 1.0 put } if
      dup 1 get 1 gt {  dup 1 1.0 put } if
      dup 2 get 1 gt {  dup 2 1.0 put } if
      dup 3 get 1 gt {  dup 3 1.0 put } if
      aload pop
      %stack: C M Y K
    }
  ]
  255
  %note: < > delimits a hexadecimal string
  <
  $deviceNLUT
  >
]
setcolorspace


%note: this is all about the reading of the image data

%note: creates a string of length width int, each of whose elements is
%%+ initialized with the integer 0
/picstr1 $width string def
/rawreaddata
{
  hasDecodeFile 0 eq
  {
    /decodeFile
      %note: These filters can be chained togerther, so if data would be
      %%+ zlib compressed and then saved as ascii85 string then the
      %%+ encoding would be:
      %%+ currentfile /ASCII85Decode filter /FlateDecode filter
      %%+ where:
      %%+ /ASCII85Decode filter decodes ascii85 encoded data and
      %%+ /FlateDecode filter decodes zlib compressed data
      currentfile
      /ASCIIHexDecode filter % decodes hex encoded data (0-0A-F)
    def
    /hasDecodeFile 1 def
  } if
  decodeFile exch readstring pop
} def

%note: beginimage will be put on the stack at the ImageBinary placeholder
/beginimage /image load def
/hasDecodeFile 0 def
/readdata /rawreaddata load bind def

%note: this is the argument dict for the image procedure
12 dict begin
/ImageType 1 def
/Width cols def
/Height rows def
%note: the image is not in postscript coordinates which start at the lower
%%+ left corner instead it starts at the upper left corner, so the matrix
%%+ here mirrors the image along the horizontal axis, the fourth value (rows)
%%+ is beeing negated with neg
/ImageMatrix [cols 0 0 rows neg 0 rows] def
/BitsPerComponent 8 def
%note: straight from PLRM -- Decode:
%%+ (Required) An array of numbers describing how to map image samples into
%%+ the range of values appropriate for the current color space; see “Sample De-
%%+ coding,” below. The length of the array must be twice the number of color
%%+ coponents in the current color space. In an image dictionary used with
%%+ imagemask, the value of this entry must be either [0 1] or [1 0].
/Decode [0 255] def  % this is typical for the INDEXED color space 
/DataSource {picstr1 readdata} def
currentdict end
%note: inject the beginimage procedure here
$ImageBinary

grestore % matches Image Header gsave Image Trailer grestore
%%EndObject
end
grestore % matches EPS gsave
"""
)


def junked(string, chunkLen):
    return [string[i:i+chunkLen] for i in range(0, len(string), chunkLen)]

# This is to remember how encoding the data with ASCII85 was done
# that encoding was much slower than hex but did use less space.
# For the saving of eps-files this might become interesting again, because
# speed of encoding is not so important in that case.
# import mom.codec as codec
#
# An alternative way to using a python module for ascii_85 encoding would
# be to use ghostscript for that matter. That would ensure compatibillity
# and would show how to use ghostscript for encoding, too.
# However this module would have an dependency on ghostscrip, then.
#
# def get_image_binary(string):
#     string = codec.base85_encode(string, codec.B85_ASCII)
#     if bytes is not str:
#         string = string.decode('utf-8')
#     string = junked(string, 65)
#     string = '\n'.join(string)
#     string = ('\nbeginimage\n{0}~>'.format(string))
#     length = len(string)
#     return '%%BeginBinary: {0}{1}\n%%EndBinary'.format(len(string), string)

def get_image_binary(binary):
    ascii = binascii.hexlify(binary)
    del binary
    if bytes is not str:
        ascii = ascii.decode('utf-8')
    ascii = junked(ascii, 65)
    ascii = '\n'.join(ascii)
    # the beginimage must be within the begin binary, so a document manager can
    # skip this part. the beginimage counts into the part that can be skipped
    ascii = ('\nbeginimage\n{0}>'.format(ascii))
    length = len(ascii)
    return '%%BeginData: {0} Hex Bytes{1}\n%%EndData'.format(len(ascii), ascii)

def get_device_n_lut(*inks):
    """
    This table has 256 indexes. For two used colors the first index
    points to two bytes (in the hex representation 4 bytes, 2 bytes
    are used for one binary byte) The first byte is for the first
    color the seccond is for the seccond color. These values are an
    representation of the curves defined in the editor as Loockup Table.
    It describes how much of the ink should be printed for whatever
    color value (between 0 and 255, like in the grayscale image)
    """
    table = []
    xs = np.linspace(1.0, 0.0, 256)
    for ink in inks:
        ip = interpolation_strategies_dict[ink.interpolation](ink.points_value)
        vals = ip(xs)
        vals = np.nan_to_num(vals)
        # no pos will be smaller than 0 or bigger than 1
        vals[vals < 0] = 0 # max(0, y)
        vals[vals > 1] = 1 # min(1, y)
        table.append(vals)
    # round to int, make bytes, transpose so that all first bytes are first,
    # its like zip()
    table = np.rint(np.array(table) * 255) \
        .astype(np.uint8) \
        .T \
        .tostring()
    table = binascii.hexlify(table).upper()
    if bytes is not str:
        table = table.decode('utf-8')
    return '\n  '.join(junked(table, 66))


process_colors = {
    'Cyan'   : (1.0, 0.0, 0.0, 0.0),
    'Magenta': (0.0, 1.0, 0.0, 0.0),
    'Yellow' : (0.0, 0.0, 1.0, 0.0),
    'Black'  : (0.0, 0.0, 0.0, 1.0)
}

def is_process_color(ink):
    return ink.name in process_colors

def escape_string(string):
    name = string.replace('\\', '\\\\')
    name = name.replace(')', '\\)')
    return name

def get_init_colors(*inks):
    process_color_value = '{0} {1} {2} {3}'
    init_process_colors_tpl = Template(\
    '/setcmykcolor where {pop\n  $value setcmykcolor\n  \
100 100 moveto 101 101 lineto stroke\n} if')
    
    custom_color_value = '{0} {1} {2} {3} ({name})'
    init_custom_colors_tpl = Template(\
    '/findcmykcustomcolor where {pop\n  $value\n  \
findcmykcustomcolor 1 setcustomcolor\n  100 100 moveto 101 101 \
lineto stroke\n} if')
    
    process_colors_init = []
    custom_colors_init  = []
    
    for ink in inks:
        
        if is_process_color(ink):
            value = process_color_value.format(*process_colors[ink.name])
            process_colors_init.append(
                init_process_colors_tpl.substitute({'value': value}))
        else:
            
            value = custom_color_value.format(*ink.cmyk, name=escape_string(ink.name))
            custom_colors_init.append(
                init_custom_colors_tpl.substitute({'value': value}))
    
    return init_colors.substitute({
        'initProcessColors': '\n'.join(process_colors_init),
        'initCustomColors' : '\n'.join(custom_colors_init)
    })
    
def get_dsc_colors(*inks):
    # this has a process color
    # %%DocumentProcessColors:  Black
    # %%DocumentCustomColors: (PANTONE 144 CVC)
    # %%CMYKCustomColor: 0.0300 0.5800 1 0 (PANTONE 144 CVC)
    #
    # this has no process color 
    # %%DocumentCustomColors: (PANTONE Black 7 C)
    # %%+ (PANTONE Warm Gray 7 CVC)
    # %%+ (PANTONE Warm Gray 2 CVC)
    # %%CMYKCustomColor: 0.67 0.63 0.63 0.57 (PANTONE Black 7 C)
    # %%CMYKCustomColor: 0.42 0.40 0.44 0.04 (PANTONE Warm Gray 7 CVC)
    # %%CMYKCustomColor: 0.15 0.13 0.17 0.00 (PANTONE Warm Gray 2 CVC)
    result = []
    process_colors = []
    custom_colors = []
    colors_separator = '\n%%+ '
    cmyk_custom_format = '%%CMYKCustomColor: {0:.4f} {1:.4f} {2:.4f} {3:.4f} ({name})'
    
    for ink in inks:
        (process_colors if is_process_color(ink) else custom_colors).append(ink)

    if len(process_colors):
        DocumentProcessColors =  colors_separator.join([
            ink.name for ink in process_colors])
        result.append('%%DocumentProcessColors: {0}'.format(DocumentProcessColors))
    if len(custom_colors):
        DocumentCustomColors = colors_separator.join([
            '({name})'.format(name=escape_string(ink.name)) for ink in custom_colors])
        result.append('%%DocumentCustomColors: {0}'.format(DocumentCustomColors))
        result += [
            cmyk_custom_format.format(*ink.cmyk, name=escape_string(ink.name)) for ink in custom_colors
        ]
    return '\n'.join(result)   

def get_duotone_names(*inks):
    # '/DuotoneNames [ /Black (PANTONE 144 CVC) ] def',
    names = [
        ('/{0}' if is_process_color(ink) else '({0})').format(escape_string(ink.name))
        for ink in inks
    ]    
    return '/DuotoneNames [ {0} ] def'.format(' '.join(names))

def get_duotone_cmyk_values(*inks):
    # /DuotoneCMYKValues [
    #   [0.0000  0.0000  0.0000 1.0000] % Black
    #   [0.0300 0.5800 1.0000 0.0000] % PANTONE 144CVC
    # ] def
    cmyk_values_format = '  [{0:.4f} {1:.4f} {2:.4f} {3:.4f}] % {name}'

    CMYKValues = '\n'.join([
        cmyk_values_format.format(
            *(process_colors[ink.name] if is_process_color(ink) else ink.cmyk),
            name=escape_string(ink.name)
        ) for ink in inks
    ])
    return '/DuotoneCMYKValues [\n{0}\n] def'.format(CMYKValues)

class EPSToolException(Exception):
    pass


class EPSTool(object):
    """ Create an eps file file from raw grayscale image pixel data and
    a list of CurvesModels
    
    This is designed to take the image data independently from the CurvesModel
    color-data. Its possible to store image data here and change the color-data
    to generate differnetly colored images with copy of the image or vice versa.
    """
    def __init__(self):
        self._mapping = {}
        self._has_color = False
        self._has_image = False
    
    def set_color_data(self, *curves):
        """ Set the colors of the eps.
        
        curves: instances of CurvesModel
        """
        self._has_color = True
        self._mapping['deviceNLUT'] = get_device_n_lut(*curves)
        self._mapping['initColors'] = get_init_colors(*curves)
        self._mapping['DSCColors'] = get_dsc_colors(*curves)
        self._mapping['DuotoneNames'] = get_duotone_names(*curves)
        self._mapping['DuotoneCMYKValues'] = get_duotone_cmyk_values(*curves)
    
    def set_image_data(self, image_bin, size):
        """Set the pixel data of the image to show in the eps document.
        
        image_bin: str or bytes, the pixel values of a grayscale image each
                   pixel should be one byte from 0 (black) to 255 (white)
        size: tuple of integers: (width, height)
              width * height should be the same as len(image_bin)
        
        """
        self._mapping['ImageBinary'] = get_image_binary(image_bin)
        self._mapping['width'], self._mapping['height'] = size
        self._has_image = True
    
    def create(self):
        """ Return a utf-8 encoded string/bytes with the EPS-data
        or raise EPSToolException if data is missing.
        """
        if not self._has_color:
            raise EPSToolException('Color information is missing, use set_color_data')
            
        if not self._has_image:
            raise EPSToolException('Image data is missing, use set_image_data')
        
        self._mapping['CreationDate'] = datetime.now().ctime()
        return eps_template.substitute(self._mapping).encode('utf-8')

if __name__== '__main__':
    import sys
    from model import ModelCurves, ModelInk
    import PIL.Image as Image
    
    curvesModel = ModelCurves(ChildModel=ModelInk)
    curvesModel.append_curve({'name':'Black', 'cmyk':(0.0, 0.0, 0.0, 1)})
    
    curvesModel.append_curve({'name':'PANTONE Greeen', 'cmyk':(0.0800, 0.0020, 0.9, 0)
        ,'interpolation':'linear'})
    
    curvesModel.append_curve({'name':'Orange', 'cmyk':(0.0, 0.1, 0.0002, 0.0040)
        ,'interpolation':'linear'})
    
    filename = sys.argv[1]
    im = Image.open(filename)
    
    epsTool = EPSTool();
    epsTool.set_color_data(*curvesModel.curves)
    epsTool.set_image_data(im.tostring(), im.size)
    print (epsTool.create())
